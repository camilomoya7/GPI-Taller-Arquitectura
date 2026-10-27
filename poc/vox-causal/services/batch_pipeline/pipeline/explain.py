"""Explicación post-llamada para el supervisor (camino frío).

Usa Azure OpenAI si está configurado (AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT,
autenticación con identidad administrada). Si no está configurado, si falla o si
excede el tiempo, cae a una plantilla determinista: la explicación nunca bloquea
ni a la llamada ni al pipeline.

El LLM solo REDACTA a partir de resultados causales ya calculados; no decide la
causa raíz ni recibe audio o datos personales (solo el identificador seudónimo).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("vox.batch.explain")

_LEVEL = {"high": "alto", "medium": "medio", "low": "bajo"}


def template_explanation(event: dict) -> str:
    final = event.get("final", {})
    risk = final.get("churn_risk", 0.0)
    level = _LEVEL.get(final.get("risk_level", "low"), "bajo")
    rc = final.get("root_cause")
    lines = [f"Llamada {event.get('call_ref', '?')[:12]}: riesgo de fuga {level} ({risk:.0%})."]
    if rc:
        lines.append(
            f"Causa raíz más probable: {rc['label']} (efecto causal estimado +{rc['effect']:.0%} "
            f"en la probabilidad de fuga)."
        )
        lines.append(f"Acción sugerida: {rc['playbook']}")
    else:
        lines.append("No se identificó una causa operativa dominante.")
    if final.get("unexplained_stress"):
        lines.append("Se detectó estrés vocal no explicado por las causas conocidas: revisar la grabación.")
    lines.append(f"Modelo {event.get('model_version', '?')}.")
    return " ".join(lines)


def explain(event: dict) -> tuple[str, str]:
    """Devuelve (texto, fuente) donde fuente es 'azure-openai' o 'template'."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    base = template_explanation(event)
    if not (endpoint and deployment):
        return base, "template"
    try:  # pragma: no cover - requiere un recurso de Azure OpenAI
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        token = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        client = AzureOpenAI(
            azure_endpoint=endpoint, azure_ad_token_provider=token,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"), timeout=8.0,
        )
        resp = client.chat.completions.create(
            model=deployment,
            temperature=0.2,
            max_tokens=180,
            messages=[
                {"role": "system", "content": (
                    "Eres un analista de calidad de un contact center. Reescribe el diagnóstico en "
                    "3 frases claras para un supervisor, en español, sin inventar datos."
                )},
                {"role": "user", "content": base},
            ],
        )
        return resp.choices[0].message.content.strip(), "azure-openai"
    except Exception as exc:  # pragma: no cover
        log.warning("azure openai no disponible, se usa plantilla: %s", exc)
        return base, "template"
