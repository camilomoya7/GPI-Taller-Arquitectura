#!/usr/bin/env bash
# =============================================================================
# Vox-Causal AI — verificación EN AZURE de las dos restricciones del incidente.
# Genera evidencia para el informe y la exposición (guárdela con:  bash verify.sh | tee evidencia.txt)
#
#   R1a  Cifrado en tránsito: HTTP redirige a HTTPS, TLS < 1.2 rechazado (API y Storage)
#   R1b  SAS de delegación: solo lectura, solo HTTPS, expira en 5 min, manipulación → 403,
#        sin acceso público ni por clave de cuenta
#   R1c  Latencia < 200 ms: llamada demo + benchmark DENTRO de UK South (job bench)
#   R2   Aislamiento: VNets sin peering, entorno batch sin ingreso público, colas de una vía
#   +    Privacidad: el canal del operador se rechaza (EU AI Act art. 5.1.f)
#   +    Camino frío: el worker consume los eventos de Service Bus y escribe auditoría
# =============================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1
# shellcheck disable=SC1091
source .deploy.env
PY="${PYTHON:-python3}"

ok()   { printf '  \033[32m✔ %s\033[0m\n' "$*"; }
bad()  { printf '  \033[31m✘ %s\033[0m\n' "$*"; }
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
expect() { # descripción esperado obtenido
  if [ "$2" = "$3" ]; then ok "$1 (HTTP $3)"; else bad "$1 (esperado $2, obtenido $3)"; fi
}
AUTH=(-H "Authorization: Bearer $API_TOKEN")

step "Estado de la API"
curl -s "https://$FQDN/ready"; echo

step "R1a · Cifrado en tránsito"
code=$(curl -s -o /dev/null -w '%{http_code}' "http://$FQDN/health")
case "$code" in 301|302|307|308) ok "HTTP plano redirige a HTTPS (HTTP $code)";; *) bad "HTTP plano respondió $code";; esac
if curl -s --tlsv1.1 --tls-max 1.1 -o /dev/null "https://$FQDN/health" 2>/dev/null; then
  bad "La API aceptó TLS 1.1"; else ok "La API rechaza TLS 1.0/1.1"; fi
if curl -s --tlsv1.1 --tls-max 1.1 -o /dev/null "https://$ST.blob.core.windows.net/" 2>/dev/null; then
  bad "Storage aceptó TLS 1.1"; else ok "Storage rechaza TLS 1.0/1.1"; fi
"$PY" - "$FQDN" <<'PY'
import socket, ssl, sys
ctx = ssl.create_default_context()
with socket.create_connection((sys.argv[1], 443), timeout=10) as s, ctx.wrap_socket(s, server_hostname=sys.argv[1]) as t:
    print(f"  ✔ Conexión negociada: {t.version()} · {t.cipher()[0]}")
PY

step "Privacidad · el canal del operador NO se analiza"
"$PY" tools/simulate_call.py --url "wss://$FQDN/v1/stream" --token "$API_TOKEN" --scenario operator_channel

step "R1c · Llamada demo en vivo (desde este computador)"
"$PY" tools/simulate_call.py --url "wss://$FQDN/v1/stream" --token "$API_TOKEN" --scenario escalation
echo "  Nota: la latencia extremo a extremo desde fuera del Reino Unido incluye la distancia de red."
echo "        La plataforma de telefonía de Alloxentric opera en la misma región; ver benchmark en región."

step "R1c · Benchmark DENTRO de $LOCATION (job $JOB_BENCH: 100, 180 y 360 llamadas simultáneas)"
EXEC=$(az containerapp job start -g "$RG" -n "$JOB_BENCH" --query name -o tsv)
echo "  ejecución: $EXEC (≈ 2 min)"
for _ in $(seq 1 60); do
  st=$(az containerapp job execution show -g "$RG" -n "$JOB_BENCH" --job-execution-name "$EXEC" \
       --query properties.status -o tsv 2>/dev/null)
  [ "$st" = "Succeeded" ] || [ "$st" = "Failed" ] && break; sleep 10
done
echo "  estado: $st"
az storage blob download --account-name "$ST" -c evidence -n bench/latest.json -f bench-azure.json \
  --auth-mode login -o none --only-show-errors && "$PY" - <<'PY'
import json
d = json.load(open("bench-azure.json"))
print(f"  Región: {d['region']}")
for r in d["results"]:
    rej = r["errors"].get("closed_1013", 0)
    print(f"  {r['streams']:>4} llamadas ofrecidas · p50 {r['p50_ms']:6.1f} ms · p95 {r['p95_ms']:6.1f} ms · "
          f"p99 {r['p99_ms']:6.1f} ms · <200 ms: {r['pct_under_200ms']:5.1f}% · derivadas a otra réplica (1013): {rej}")
PY
echo "  Métricas del servidor:"; curl -s "${AUTH[@]}" "https://$FQDN/metrics"; echo

step "R1b · SAS de delegación de usuario sobre una grabación"
REF="demo$(date +%s)"
"$PY" tools/make_wav.py "/tmp/$REF.wav" >/dev/null
az storage blob upload --account-name "$ST" -c recordings -n "$REF.wav" -f "/tmp/$REF.wav" --auth-mode login \
  --overwrite -o none --only-show-errors && ok "Grabación sintética subida con identidad (sin claves)"
RESP=$(curl -s -X POST "${AUTH[@]}" "https://$FQDN/v1/recordings/$REF/access")
echo "  respuesta: $(echo "$RESP" | "$PY" -c 'import json,sys;d=json.load(sys.stdin);d["url"]=d["url"][:90]+"…";print(d)')"
URL=$(echo "$RESP" | "$PY" -c 'import json,sys;print(json.load(sys.stdin)["url"])')
expect "Descarga por HTTPS con la SAS" 200 "$(curl -s -o /dev/null -w '%{http_code}' "$URL")"
code=$(curl -s -o /dev/null -w '%{http_code}' "${URL/https:/http:}")
case "$code" in 400|403) ok "La misma SAS por HTTP es rechazada (HTTP $code)";; *) bad "HTTP respondió $code";; esac
expect "SAS manipulada (sp=r → sp=rw) es rechazada" 403 "$(curl -s -o /dev/null -w '%{http_code}' "${URL/sp=r&/sp=rw&}")"
expect "Escritura con SAS de solo lectura es rechazada" 403 \
  "$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H 'x-ms-blob-type: BlockBlob' --data 'x' "$URL")"
code=$(curl -s -o /dev/null -w '%{http_code}' "https://$ST.blob.core.windows.net/recordings/$REF.wav")
case "$code" in 401|403|404|409) ok "Sin SAS no hay acceso anónimo (HTTP $code)";; *) bad "Acceso anónimo respondió $code";; esac
if az storage blob list --account-name "$ST" -c recordings --auth-mode key -o none 2>/dev/null; then
  bad "Se permitió acceso con clave de cuenta"; else ok "Acceso con clave de cuenta deshabilitado"; fi
"$PY" - "$URL" <<'PY'
import sys, urllib.parse as u
q = u.parse_qs(u.urlparse(sys.argv[1]).query)
print(f"  ✔ Parámetros SAS: spr={q['spr'][0]} sp={q['sp'][0]} se={q['se'][0]} (firmada por Entra ID: skoid presente={'skoid' in q})")
PY

step "Camino frío · worker consume Service Bus y escribe auditoría"
EXEC=$(az containerapp job start -g "$RG" -n "$JOB_WORKER" --query name -o tsv)
for _ in $(seq 1 30); do
  st=$(az containerapp job execution show -g "$RG" -n "$JOB_WORKER" --job-execution-name "$EXEC" \
       --query properties.status -o tsv 2>/dev/null)
  [ "$st" = "Succeeded" ] || [ "$st" = "Failed" ] && break; sleep 10
done
echo "  estado del worker: $st"
az storage blob list --account-name "$ST" -c audit --auth-mode login --query "[].name" -o tsv | tail -3

step "R2 · Aislamiento entre zonas"
peer=$(az network vnet peering list -g "$RG" --vnet-name "vnet-${PREFIX}-rt" --query "length(@)" -o tsv)
[ "$peer" = "0" ] && ok "vnet-rt y vnet-batch sin peering (sin ruta de red entre zonas)" || bad "Existe peering"
internal=$(az containerapp env show -g "$RG" -n "$ENV_BATCH" --query properties.vnetConfiguration.internal -o tsv)
[ "$internal" = "true" ] && ok "Entorno batch sin ingreso público (internal-only)" || bad "Entorno batch público"
az role assignment list --all --query "[?contains(scope,'$SB')].{rol:roleDefinitionName, ambito:scope}" -o table \
  | sed 's#/subscriptions/[^ ]*/queues/#…/queues/#'
echo
echo "Fin de la verificación."
