#!/usr/bin/env bash
# =============================================================================
# Vox-Causal AI — despliegue de la prueba de concepto en Azure (UK South)
#
# Crea DOS ZONAS AISLADAS (restricción 2) y aplica cifrado en tránsito + SAS de
# delegación de usuario (restricción 1):
#
#   Zona A · tiempo real   vnet-rt (10.10/16) → cae-rt   → ca-api   (WSS, TLS 1.2+, réplicas 1..10)
#   Zona B · batch         vnet-batch (10.20/16, SIN peering, entorno interno sin ingreso público)
#                          → cae-batch → jobs worker / train
#   Pruebas                cae-test → job bench (cliente de carga en la misma región)
#
#   Contrato único entre zonas: el modelo aprobado viaja dentro de la imagen de la API.
#   Mensajería de una sola vía: API → Service Bus (Sender) → worker (Receiver).
#
# Requisitos: Azure CLI ≥ 2.60, sesión iniciada (az login) con rol Owner en la suscripción.
# Uso (desde poc/vox-causal):   bash deploy/azure/deploy.sh
# Variables opcionales: LOCATION, PREFIX, RG, BUILD_MODE=acr|docker, USE_KEYVAULT=true|false
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

LOCATION="${LOCATION:-uksouth}"
PREFIX="${PREFIX:-voxcausal}"
RG="${RG:-rg-${PREFIX}-poc}"
BUILD_MODE="${BUILD_MODE:-acr}"
USE_KEYVAULT="${USE_KEYVAULT:-true}"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}"

step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
retry() { local n=0; until "$@"; do n=$((n+1)); [ $n -ge 12 ] && return 1; echo "  … reintentando ($n) mientras se propagan permisos"; sleep 10; done; }

step "0. Verificando sesión y extensiones"
az account show --query "{suscripcion:name, id:id}" -o table
SUB_ID=$(az account show --query id -o tsv)
SUFFIX="${SUFFIX:-$(printf '%s' "$SUB_ID$RG" | sha256sum | cut -c1-6)}"
ACR="cr${PREFIX}${SUFFIX}"
ST="st${PREFIX}${SUFFIX}"
SB="sb-${PREFIX}-${SUFFIX}"
KV="kv-${PREFIX}-${SUFFIX}"
LAW="log-${PREFIX}"
ENV_RT="cae-${PREFIX}-rt"; ENV_BATCH="cae-${PREFIX}-batch"; ENV_TEST="cae-${PREFIX}-test"
API="ca-${PREFIX}-api"
JOB_WORKER="caj-${PREFIX}-worker"; JOB_TRAIN="caj-${PREFIX}-train"; JOB_BENCH="caj-${PREFIX}-bench"
QUEUE="call-closed"
az extension add --name containerapp --upgrade --only-show-errors >/dev/null
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.ServiceBus \
          Microsoft.Storage Microsoft.KeyVault Microsoft.ManagedIdentity Microsoft.Network; do
  az provider register --namespace "$ns" --wait --only-show-errors >/dev/null
done
ME=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || az account show --query user.name -o tsv)

step "1. Grupo de recursos en $LOCATION (residencia de datos UK GDPR)"
az group create -n "$RG" -l "$LOCATION" --tags project=vox-causal-poc data-classification=personal-pseudonymized \
  -o none

step "2. Observabilidad: Log Analytics (telemetría y auditoría)"
az monitor log-analytics workspace create -g "$RG" -n "$LAW" -l "$LOCATION" --retention-time 30 -o none
LAW_ID=$(az monitor log-analytics workspace show -g "$RG" -n "$LAW" --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g "$RG" -n "$LAW" --query primarySharedKey -o tsv)

step "3. Redes separadas SIN peering (aislamiento de red entre zonas)"
for zone in rt:10.10 batch:10.20; do
  name="${zone%%:*}"; net="${zone##*:}"
  az network vnet create -g "$RG" -n "vnet-${PREFIX}-${name}" -l "$LOCATION" --address-prefixes "${net}.0.0/16" \
    --subnet-name snet-aca --subnet-prefixes "${net}.0.0/23" -o none
  az network vnet subnet update -g "$RG" --vnet-name "vnet-${PREFIX}-${name}" -n snet-aca \
    --delegations Microsoft.App/environments -o none
done
SUBNET_RT=$(az network vnet subnet show -g "$RG" --vnet-name "vnet-${PREFIX}-rt" -n snet-aca --query id -o tsv)
SUBNET_BATCH=$(az network vnet subnet show -g "$RG" --vnet-name "vnet-${PREFIX}-batch" -n snet-aca --query id -o tsv)

step "4. Registro de contenedores (sin usuario admin: solo identidades administradas)"
az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled false -l "$LOCATION" -o none
ACR_SERVER=$(az acr show -n "$ACR" --query loginServer -o tsv)
ACR_ID=$(az acr show -n "$ACR" --query id -o tsv)

step "5. Construyendo imágenes ($BUILD_MODE) con tag $TAG"
if [ "$BUILD_MODE" = "acr" ]; then
  az acr build -r "$ACR" -t "vox-inference-api:$TAG" -f services/inference_api/Dockerfile . --only-show-errors -o none
  az acr build -r "$ACR" -t "vox-batch:$TAG" -f services/batch_pipeline/Dockerfile . --only-show-errors -o none
else
  az acr login -n "$ACR"
  docker build -f services/inference_api/Dockerfile -t "$ACR_SERVER/vox-inference-api:$TAG" .
  docker build -f services/batch_pipeline/Dockerfile -t "$ACR_SERVER/vox-batch:$TAG" .
  docker push "$ACR_SERVER/vox-inference-api:$TAG"
  docker push "$ACR_SERVER/vox-batch:$TAG"
fi

step "6. Identidades administradas (una por zona, mínimo privilegio)"
for who in api batch test; do az identity create -g "$RG" -n "id-${PREFIX}-${who}" -l "$LOCATION" -o none; done
idv() { az identity show -g "$RG" -n "id-${PREFIX}-$1" --query "$2" -o tsv; }
ID_API=$(idv api id); ID_API_CLIENT=$(idv api clientId); ID_API_PRINCIPAL=$(idv api principalId)
ID_BATCH=$(idv batch id); ID_BATCH_CLIENT=$(idv batch clientId); ID_BATCH_PRINCIPAL=$(idv batch principalId)
ID_TEST=$(idv test id); ID_TEST_CLIENT=$(idv test clientId); ID_TEST_PRINCIPAL=$(idv test principalId)

role() { az role assignment create --assignee-object-id "$1" --assignee-principal-type "$2" --role "$3" --scope "$4" \
         -o none --only-show-errors; }
for p in "$ID_API_PRINCIPAL" "$ID_BATCH_PRINCIPAL" "$ID_TEST_PRINCIPAL"; do role "$p" ServicePrincipal AcrPull "$ACR_ID"; done

step "7. Almacenamiento: TLS ≥ 1.2, solo HTTPS, sin claves compartidas, sin acceso público"
az storage account create -g "$RG" -n "$ST" -l "$LOCATION" --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --https-only true --allow-shared-key-access false --allow-blob-public-access false \
  --default-action Allow -o none
ST_ID=$(az storage account show -g "$RG" -n "$ST" --query id -o tsv)
role "$ME" User "Storage Blob Data Contributor" "$ST_ID" || true
for c in recordings audit model-registry evidence; do
  retry az storage container create --account-name "$ST" -n "$c" --auth-mode login -o none --only-show-errors
done
# UK GDPR · limitación del plazo de conservación: grabaciones se eliminan a los 30 días.
POLICY_FILE=$(mktemp)
cat > "$POLICY_FILE" <<'JSON'
{"rules":[{"enabled":true,"name":"gdpr-retention-recordings","type":"Lifecycle",
  "definition":{"actions":{"baseBlob":{"delete":{"daysAfterModificationGreaterThan":30}}},
  "filters":{"blobTypes":["blockBlob"],"prefixMatch":["recordings/"]}}}]}
JSON
az storage account management-policy create -g "$RG" --account-name "$ST" --policy @"$POLICY_FILE" -o none
# API: puede pedir claves de delegación y LEER grabaciones (para emitir SAS de solo lectura). Nada más.
role "$ID_API_PRINCIPAL" ServicePrincipal "Storage Blob Delegator" "$ST_ID"
role "$ID_API_PRINCIPAL" ServicePrincipal "Storage Blob Data Reader" "$ST_ID/blobServices/default/containers/recordings"
# Batch: escribe auditoría y registro de modelos.
role "$ID_BATCH_PRINCIPAL" ServicePrincipal "Storage Blob Data Contributor" "$ST_ID/blobServices/default/containers/audit"
role "$ID_BATCH_PRINCIPAL" ServicePrincipal "Storage Blob Data Contributor" \
  "$ST_ID/blobServices/default/containers/model-registry"
# Zona de pruebas: solo puede dejar resultados del benchmark en "evidence".
role "$ID_TEST_PRINCIPAL" ServicePrincipal "Storage Blob Data Contributor" "$ST_ID/blobServices/default/containers/evidence"

step "8. Service Bus (solo autenticación Entra ID; API = emisor, batch = receptor)"
az servicebus namespace create -g "$RG" -n "$SB" -l "$LOCATION" --sku Basic --disable-local-auth true -o none
az servicebus queue create -g "$RG" --namespace-name "$SB" -n "$QUEUE" -o none
Q_ID=$(az servicebus queue show -g "$RG" --namespace-name "$SB" -n "$QUEUE" --query id -o tsv)
role "$ID_API_PRINCIPAL" ServicePrincipal "Azure Service Bus Data Sender" "$Q_ID"
role "$ID_BATCH_PRINCIPAL" ServicePrincipal "Azure Service Bus Data Receiver" "$Q_ID"

step "9. Secretos"
# En re-ejecuciones se conservan el token y la clave de seudonimización (los seudónimos deben ser estables).
if [ -f "$ROOT/.deploy.env" ]; then API_TOKEN="${API_TOKEN:-$(grep '^API_TOKEN=' "$ROOT/.deploy.env" | cut -d= -f2-)}"; fi
API_TOKEN="${API_TOKEN:-$(openssl rand -hex 24)}"
PSEUDONYM_KEY="$(openssl rand -hex 32)"
if [ "$USE_KEYVAULT" = "true" ]; then
  az keyvault create -g "$RG" -n "$KV" -l "$LOCATION" --enable-rbac-authorization true -o none
  KV_ID=$(az keyvault show -n "$KV" --query id -o tsv); KV_URI=$(az keyvault show -n "$KV" --query properties.vaultUri -o tsv)
  role "$ME" User "Key Vault Secrets Officer" "$KV_ID" || true
  role "$ID_API_PRINCIPAL" ServicePrincipal "Key Vault Secrets User" "$KV_ID"
  role "$ID_TEST_PRINCIPAL" ServicePrincipal "Key Vault Secrets User" "$KV_ID"
  retry az keyvault secret set --vault-name "$KV" -n api-token --value "$API_TOKEN" -o none
  if ! az keyvault secret show --vault-name "$KV" -n pseudonym-key -o none 2>/dev/null; then
    retry az keyvault secret set --vault-name "$KV" -n pseudonym-key --value "$PSEUDONYM_KEY" -o none
  fi
  SECRETS_API=("api-token=keyvaultref:${KV_URI}secrets/api-token,identityref:${ID_API}"
               "pseudonym-key=keyvaultref:${KV_URI}secrets/pseudonym-key,identityref:${ID_API}")
  SECRETS_TEST=("api-token=keyvaultref:${KV_URI}secrets/api-token,identityref:${ID_TEST}")
else
  SECRETS_API=("api-token=$API_TOKEN" "pseudonym-key=$PSEUDONYM_KEY")
  SECRETS_TEST=("api-token=$API_TOKEN")
fi
echo "  esperando 60 s a que se propaguen los permisos RBAC…"; sleep 60

step "10. Entornos de Container Apps (zona A pública, zona B solo interna)"
az containerapp env create -g "$RG" -n "$ENV_RT" -l "$LOCATION" --logs-workspace-id "$LAW_ID" \
  --logs-workspace-key "$LAW_KEY" --infrastructure-subnet-resource-id "$SUBNET_RT" --enable-workload-profiles -o none
az containerapp env create -g "$RG" -n "$ENV_BATCH" -l "$LOCATION" --logs-workspace-id "$LAW_ID" \
  --logs-workspace-key "$LAW_KEY" --infrastructure-subnet-resource-id "$SUBNET_BATCH" --internal-only true \
  --enable-workload-profiles -o none
az containerapp env create -g "$RG" -n "$ENV_TEST" -l "$LOCATION" --logs-workspace-id "$LAW_ID" \
  --logs-workspace-key "$LAW_KEY" -o none

step "11. API de inferencia (camino caliente): 1 vCPU por réplica, 180 sesiones, 1..10 réplicas"
API_ENV=(AZURE_CLIENT_ID="$ID_API_CLIENT" API_TOKEN=secretref:api-token PSEUDONYM_KEY=secretref:pseudonym-key
         MAX_SESSIONS=180 LATENCY_BUDGET_MS=200 SERVICEBUS_FQDN="${SB}.servicebus.windows.net"
         SERVICEBUS_QUEUE="$QUEUE" STORAGE_ACCOUNT_URL="https://${ST}.blob.core.windows.net"
         RECORDINGS_CONTAINER=recordings SAS_TTL_MINUTES=5 DATA_REGION="$LOCATION")
if az containerapp show -g "$RG" -n "$API" -o none 2>/dev/null; then
  az containerapp update -g "$RG" -n "$API" --image "$ACR_SERVER/vox-inference-api:$TAG" -o none
else
  # min-replicas 1: sin arranque en frío (la latencia < 200 ms aplica desde la primera llamada).
  # Escala por conexiones concurrentes: 150 por réplica (el tope duro por réplica es 180).
  az containerapp create -g "$RG" -n "$API" --environment "$ENV_RT" \
    --image "$ACR_SERVER/vox-inference-api:$TAG" --registry-server "$ACR_SERVER" --registry-identity "$ID_API" \
    --user-assigned "$ID_API" --ingress external --target-port 8000 --transport auto \
    --cpu 1.0 --memory 2.0Gi --min-replicas 1 --max-replicas 10 \
    --scale-rule-name concurrent-calls --scale-rule-type http --scale-rule-http-concurrency 150 \
    --secrets "${SECRETS_API[@]}" --env-vars "${API_ENV[@]}" -o none
fi
FQDN=$(az containerapp show -g "$RG" -n "$API" --query properties.configuration.ingress.fqdn -o tsv)

step "12. Jobs del camino frío (zona B) y job de benchmark (pruebas)"
BATCH_IMG="$ACR_SERVER/vox-batch:$TAG"
job() { # nombre entorno identidad cpu memoria timeout env...
  local name=$1 env=$2 ident=$3 cpu=$4 mem=$5 timeout=$6; shift 6
  if az containerapp job show -g "$RG" -n "$name" -o none 2>/dev/null; then
    az containerapp job update -g "$RG" -n "$name" --image "$BATCH_IMG" -o none
  else
    az containerapp job create -g "$RG" -n "$name" --environment "$env" --trigger-type Manual \
      --replica-timeout "$timeout" --replica-retry-limit 0 --parallelism 1 --replica-completion-count 1 \
      --image "$BATCH_IMG" --registry-server "$ACR_SERVER" --registry-identity "$ident" \
      --mi-user-assigned "$ident" --cpu "$cpu" --memory "$mem" "$@" -o none
  fi
}
job "$JOB_WORKER" "$ENV_BATCH" "$ID_BATCH" 1.0 2.0Gi 1800 --env-vars JOB_MODE=worker AZURE_CLIENT_ID="$ID_BATCH_CLIENT" \
  SERVICEBUS_FQDN="${SB}.servicebus.windows.net" SERVICEBUS_QUEUE="$QUEUE" \
  AUDIT_BLOB_ACCOUNT_URL="https://${ST}.blob.core.windows.net"
job "$JOB_TRAIN" "$ENV_BATCH" "$ID_BATCH" 2.0 4.0Gi 3600 --env-vars JOB_MODE=train AZURE_CLIENT_ID="$ID_BATCH_CLIENT" \
  TRAIN_REPLICAS=3 REGISTRY_BLOB_ACCOUNT_URL="https://${ST}.blob.core.windows.net"
job "$JOB_BENCH" "$ENV_TEST" "$ID_TEST" 2.0 4.0Gi 900 --secrets "${SECRETS_TEST[@]}" --env-vars JOB_MODE=bench \
  API_WS_URL="wss://${FQDN}/v1/stream" API_TOKEN=secretref:api-token BENCH_SWEEP=100,180,360 BENCH_SECONDS=20 \
  AZURE_CLIENT_ID="$ID_TEST_CLIENT" BENCH_RESULTS_ACCOUNT_URL="https://${ST}.blob.core.windows.net" BENCH_REGION="$LOCATION"

step "13. Listo"
cat > "$ROOT/.deploy.env" <<EOF
RG=$RG
LOCATION=$LOCATION
API=$API
FQDN=$FQDN
API_TOKEN=$API_TOKEN
ST=$ST
SB=$SB
KV=$KV
LAW=$LAW
ENV_RT=$ENV_RT
ENV_BATCH=$ENV_BATCH
JOB_WORKER=$JOB_WORKER
JOB_TRAIN=$JOB_TRAIN
JOB_BENCH=$JOB_BENCH
PREFIX=$PREFIX
EOF
echo "API:      https://$FQDN   (WebSocket: wss://$FQDN/v1/stream)"
echo "Variables guardadas en .deploy.env (NO subir a Git). Siguiente paso: bash deploy/azure/verify.sh"
