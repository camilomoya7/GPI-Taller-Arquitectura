#!/usr/bin/env bash
# Elimina TODOS los recursos de la prueba de concepto (evita costos después de la demo).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/.deploy.env"
read -r -p "Se eliminará el grupo $RG y todo su contenido. ¿Continuar? (s/N) " ans
[ "${ans:-N}" = "s" ] || { echo "Cancelado."; exit 0; }
if az keyvault show -n "$KV" -o none 2>/dev/null; then
  az keyvault delete -n "$KV" -o none && az keyvault purge -n "$KV" -o none || true
fi
az group delete -n "$RG" --yes --no-wait
echo "Eliminación en curso (≈ 10 min). Verifique con: az group exists -n $RG"
