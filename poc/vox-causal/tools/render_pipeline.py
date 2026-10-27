"""Diagrama del Pipeline MLOps e Inferencia (infografía por carriles, estilo Parte 1).

Todas las cifras se leen de los archivos de resultados y del código (tools/architecture_claims.py).
Salida: docs/diagrams/Pipeline_MLOps_Inferencia.png (+ .html fuente)
Requiere Node.js con Playwright (Chromium) para la captura.
"""

from __future__ import annotations

import importlib.util
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "diagrams"
_spec = importlib.util.spec_from_file_location("architecture_claims", ROOT / "tools" / "architecture_claims.py")
claims = importlib.util.module_from_spec(_spec)
sys.modules["architecture_claims"] = claims
_spec.loader.exec_module(claims)
M = claims.measured()
S = claims._settings()
RESULTS = claims.run_all()
VERIFIED = sum(ok for _, ok, _ in RESULTS)


def es(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


st = M["stages"]
ov = M["overload"]
err_max = max(M["ate_error_dml"].values())
naive_max = max(M["ate_error_naive"].values())


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


DS = M["dataset"]
USED_PCT = M["stages"]["server_total"]["p95_ms"] / S.latency_budget_ms * 100


def step(n: int, title: str, head: str, body: str, foot: str) -> str:
    return (f'<div class="step"><div class="chev"><span class="num">{n}</span>{escape(title)}</div>'
            f'<div class="card"><h4>{escape(head)}</h4><p>{body}</p><div class="foot">{foot}</div></div></div>')


LANE_A = [
    (1, "Ingesta", "Audio y contexto en vivo",
     "La plataforma de telefonía abre un WebSocket seguro: mensaje <i>start</i> con el contexto de la llamada y tramas PCM16 de 100 ms.",
     "<b>Entrada:</b> WSS · TLS 1.2+ · <code>ws_handler.py</code>"),
    (2, "Validación", "Seguridad y privacidad",
     f"Token Bearer, canal = cliente (el del operador se rechaza: EU AI Act), formato de audio y admisión de {S.max_sessions} sesiones por réplica.",
     "<b>Cierres:</b> 1008 política · 1013 sin capacidad · <code>privacy.py</code>"),
    (3, "Preprocesamiento", "Ventana deslizante",
     f"Decodifica PCM16, descarta el canal del operador y evalúa la última ventana de {S.window_ms} ms cada {S.hop_ms} ms; si hay ráfagas, solo la más reciente.",
     "<b>Audio solo en memoria</b> · <code>stream.py</code>"),
    (4, "Rasgos prosódicos", "Tono, energía, jitter",
     "7 rasgos con la librería compartida con el batch (misma función en entrenamiento y en servicio: sin desfase).",
     f"<b>Medido:</b> p95 {es(st['prosody']['p95_ms'])} ms · <code>voxfeatures</code>"),
    (5, "Invocación del modelo", "SCM precalculado",
     "Estrés desde la voz, riesgo de fuga y causa raíz = mayor efecto causal (ATE) entre las causas activas. No se reestima nada en vivo.",
     f"<b>Medido:</b> p95 {es(st['scm']['p95_ms'])} ms · <code>scm_runtime.py</code>"),
    (6, "Entrega", "Diagnóstico al operador",
     f"JSON cada {S.hop_ms} ms con causa raíz, acción sugerida, riesgo y tiempos por etapa a la consola del operador.",
     f"<b>Servidor p95:</b> {es(st['server_total']['p95_ms'])} ms · <b>e2e p95:</b> {es(M['p95_180'], 0)} ms ({S.max_sessions} llamadas)"),
    (7, "Cierre", "Evento hacia el batch",
     "Al terminar la llamada se publica <i>call.closed</i> (sin audio, id seudónimo) en Service Bus, sin esperar respuesta.",
     "<b>Salida:</b> AMQP · TLS · no bloqueante · <code>events.py</code>"),
]

LANE_B = [
    (1, "Datos", "Efecto causal conocido", f"SCM con 3 causas, 3 confusores y mediador (estrés); {miles(DS['n'])} llamadas × {DS['replicas']} réplicas.",
     "<code>synthetic.py</code>"),
    (2, "Identificación", "DAG + backdoor", "DoWhy identifica el conjunto de ajuste de cada causa sobre el grafo.",
     "<code>train.py</code> · DoWhy"),
    (3, "Estimación", "Double ML", "EconML LinearDML con validación cruzada; también regresión ajustada como contraste.",
     "EconML <code>LinearDML</code>"),
    (4, "Refutación", "3 pruebas", "Placebo (≈ 0), causa común aleatoria (estable) y subconjunto 80 % (estable).",
     f"<b>Resultado:</b> {M['refutations_passed']}/{M['refutations_total']} aprobadas"),
    (5, "Calibración", "Voz → estrés", "Ajuste de rasgos prosódicos a estrés con voz sintética etiquetada.",
     f"<b>MAE</b> {es(M['stress_mae'], 3)} · <b>R²</b> {es(M['stress_r2'], 3)}"),
    (6, "Control de calidad", "Puerta de publicación", "Publica solo si error ATE ≤ 0,05 y todas las refutaciones pasan; si no, va a <i>rejected/</i>.",
     f"<b>Medido:</b> error máx. {es(err_max, 4)} (correlacional {es(naive_max, 4)} ✘)"),
    (7, "Registro", "Versión + SHA-256", "Artefacto JSON versionado con huella y métricas; copia en Blob <i>model-registry</i>.",
     "<code>registry.py</code>"),
    (8, "Promoción", "CI", "Verifica la huella, commit, CI (lint, pruebas, cobertura ≥ 85 %) y construye una imagen nueva.",
     "<code>promote_model.py</code> · GitHub Actions"),
    (9, "Despliegue", "Revisión inmutable", "Nueva revisión de Container Apps con el modelo dentro de la imagen; sin acceso al batch.",
     "<code>deploy.sh</code>"),
    (10, "Monitoreo", "Retroalimentación", "Latencia por etapa, rechazos por capacidad, eventos y explicaciones alimentan el reentrenamiento.",
     "Log Analytics · <code>/metrics</code>"),
]

LANE_C = [
    (1, "Cola", "Service Bus", "Cola <i>call-closed</i>, solo Entra ID: la API solo envía, el batch solo recibe.", "AMQP · TLS"),
    (2, "Worker", "Container Apps Job", "Consume los eventos pendientes en la zona batch (sin ingreso público).", "<code>worker.py</code>"),
    (3, "Explicación", "Para el supervisor", "Azure OpenAI redacta en 3 frases a partir del resultado causal; sin acceso, plantilla determinista.",
     "<code>explain.py</code> · identidad administrada"),
    (4, "Auditoría", "Registro inmutable", "Explicación, versión de modelo y seudónimo se guardan en Blob <i>audit</i>.", "HTTPS · sin claves"),
]

FALLBACKS = [
    ("Modelo ausente o manipulado (SHA-256)", "En producción la API no arranca (modo estricto); en desarrollo, reglas y alerta de auditoría"),
    ("Silencio o audio de mala calidad", "Estrés estimado desde el contexto · <i>prosody_quality: low</i>"),
    ("Réplica sin capacidad", f"Cierre 1013 → otra réplica · con {ov['streams']} ofrecidas: p95 {es(ov['p95_ms'], 0)} ms y {ov['errors'].get('closed_1013', 0)} derivadas"),
    ("Service Bus no responde (> 3 s)", "Outbox local para reintento; la llamada no se afecta"),
    ("Azure OpenAI no disponible", "Plantilla determinista con la misma información"),
    ("Canal del operador", "Rechazo 1008 + evento de auditoría <i>channel_rejected</i>"),
]


def lane(code: str, title: str, badge: str, note: str, steps, cls: str) -> str:
    inner = "".join(step(*s) for s in steps)
    return (f'<section class="lane {cls}"><header><span class="tag">{code}</span><h3>{escape(title)}</h3>'
            f'<span class="badge">{escape(badge)}</span><span class="note">{note}</span></header>'
            f'<div class="steps n{len(steps)}">{inner}</div></section>')


def html() -> str:
    fb = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in FALLBACKS)
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Pipeline MLOps e Inferencia — Vox-Causal AI</title>
<style>
:root{{--a:#a3237f;--a2:#c2349b;--b:#1f7a4d;--b2:#2e8b57;--c:#1f6fb2;--c2:#3b82c4;--ink:#16202a;--mut:#5b6875;--line:#d9e0e7}}
*{{box-sizing:border-box}} body{{margin:0;background:#fff;font-family:Inter,"Segoe UI",Arial,sans-serif;color:var(--ink);width:2400px;padding:36px 44px}}
h1{{margin:0;font-size:40px;letter-spacing:-.5px}} .sub{{color:var(--mut);font-size:19px;margin:6px 0 18px}}
.top{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid var(--ink);padding-bottom:14px;margin-bottom:22px}}
.leg{{display:flex;gap:18px;font-size:16px;color:var(--mut)}} .leg i{{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}}
.lane{{border:2px solid var(--line);border-radius:14px;padding:16px 18px 18px;margin-bottom:20px}}
.lane header{{display:flex;align-items:center;gap:14px;margin-bottom:12px}}
.lane h3{{margin:0;font-size:25px}} .tag{{color:#fff;font-weight:800;font-size:20px;border-radius:8px;padding:4px 12px}}
.badge{{background:#1f9d55;color:#fff;font-size:14px;font-weight:700;border-radius:20px;padding:4px 12px}} .note{{color:var(--mut);font-style:italic;font-size:16px}}
.A{{background:#fdf5fb;border-color:#e7b5d9}} .A .tag,.A .chev{{background:var(--a)}} .A .chev:nth-child(odd){{background:var(--a2)}}
.B{{background:#f2faf5;border-color:#b5dcc4}} .B .tag,.B .chev{{background:var(--b)}}
.C{{background:#f2f7fd;border-color:#b8d3ef}} .C .tag,.C .chev{{background:var(--c)}}
.steps{{display:grid;gap:10px}} .n7{{grid-template-columns:repeat(7,1fr)}} .n10{{grid-template-columns:repeat(5,1fr)}} .n4{{grid-template-columns:repeat(4,1fr)}}
.chev{{color:#fff;font-weight:700;font-size:18px;padding:10px 26px 10px 14px;clip-path:polygon(0 0,calc(100% - 18px) 0,100% 50%,calc(100% - 18px) 100%,0 100%);display:flex;align-items:center;gap:10px}}
.num{{background:rgba(255,255,255,.25);border-radius:50%;width:26px;height:26px;display:inline-flex;align-items:center;justify-content:center;font-size:15px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-top:6px;min-height:178px;display:flex;flex-direction:column}}
.card h4{{margin:0 0 6px;font-size:17px}} .card p{{margin:0;font-size:15px;line-height:1.38;color:#2c3a47;flex:1}}
.foot{{border-top:1px dashed var(--line);margin-top:10px;padding-top:7px;font-size:13.5px;color:var(--mut)}}
code{{font-family:"DejaVu Sans Mono",monospace;font-size:12.5px;background:#eef2f6;border-radius:4px;padding:1px 4px}}
.bar{{background:#fff7e0;border:1px solid #f0d27a;border-radius:10px;padding:12px 16px;font-size:16px;margin-top:12px}}
.budget{{display:flex;gap:0;margin-top:8px;border-radius:6px;overflow:hidden;font-size:14px;font-weight:600;color:#fff}}
.budget div{{padding:7px 10px}}
.grid2{{display:grid;grid-template-columns:1.25fr 1fr;gap:20px}}
table{{width:100%;border-collapse:collapse;font-size:15.5px}} th{{text-align:left;background:#eef2f6;padding:8px 10px}} td{{padding:8px 10px;border-top:1px solid var(--line);vertical-align:top}}
.box{{border:2px solid var(--line);border-radius:14px;padding:14px 18px}} .box h3{{margin:0 0 10px;font-size:22px}}
.tele li{{margin:6px 0;font-size:16px}}
.sep{{background:var(--ink);color:#fff;border-radius:12px;padding:16px 20px;margin-top:20px;font-size:18px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}}
.pill{{background:#fff;color:var(--ink);border-radius:6px;padding:4px 10px;font-weight:600}} .pill2{{background:#3d4b59;border-radius:6px;padding:4px 10px}}
.ver{{margin-top:12px;color:var(--mut);font-size:15px}}
</style></head><body>
<div class="top"><div><h1>Pipeline MLOps e Inferencia — Vox-Causal AI</h1>
<div class="sub">Grupo N.º 1 · Sección 411 · Caso PIA Alloxentric SpA (Azure UK South) · cifras medidas en la prueba de concepto · modelo {escape(M['model_version'])}</div></div>
<div class="leg"><span><i style="background:var(--a)"></i>Camino caliente</span><span><i style="background:var(--b)"></i>Camino frío</span><span><i style="background:var(--c)"></i>Post-llamada</span><span><i style="background:#f2a900"></i>Control</span></div></div>

{lane("A", "Camino caliente · inferencia en vivo durante la llamada", "Implementado", f"objetivo &lt; {int(S.latency_budget_ms)} ms · sin Service Bus, OpenAI ni DoWhy en la ruta", LANE_A, "A")}
<div class="bar"><b>Presupuesto de latencia (diseño) vs. medido:</b>
<div class="budget"><div style="background:#7d8a96;flex:40">red + gateway 40 ms</div><div style="background:#a3237f;flex:50">rasgos 50 ms</div><div style="background:#c2349b;flex:30">modelo 30 ms</div><div style="background:#7d8a96;flex:20">entrega 20</div><div style="background:#1f9d55;flex:60">margen 60 ms</div></div>
<div style="margin-top:6px">Medido en servidor: rasgos p95 {es(st['prosody']['p95_ms'])} ms · modelo p95 {es(st['scm']['p95_ms'])} ms · total p95 {es(st['server_total']['p95_ms'])} ms ({miles(st['server_total']['count'])} inferencias, 1 vCPU) — el servidor usa el {es(USED_PCT, 1)} % del presupuesto.</div></div>
<br/>
{lane("B", "Camino frío · entrenamiento, validación y promoción del modelo causal", "Implementado", "nunca se ejecuta durante la llamada · zona B sin ingreso público", LANE_B, "B")}
{lane("C", "Post-llamada · explicación y auditoría asíncronas", "Implementado", "desacoplado por cola de una sola vía", LANE_C, "C")}

<div class="grid2">
<div class="box"><h3>Manejo de errores y respaldos (fallbacks)</h3><table><tr><th>Falla</th><th>Respuesta del sistema</th></tr>{fb}</table></div>
<div class="box"><h3>Telemetría y auditoría</h3><ul class="tele">
<li><b>Logs JSON</b> a stdout → Log Analytics (Container Apps), id de llamada siempre seudónimo (HMAC-SHA256).</li>
<li><b>/metrics:</b> p50 / p95 / p99 por etapa (rasgos, modelo, total), sesiones activas, <i>budget_exceeded</i>, rechazos por capacidad.</li>
<li><b>Eventos de auditoría:</b> <i>model_loaded</i> (versión + SHA-256), <i>model_fallback</i>, <i>sas_issued</i> (blob, permisos, expiración), <i>channel_rejected</i>, <i>call_closed</i>.</li>
<li><b>Benchmark en región:</b> job <i>bench</i> en UK South deja resultados en Blob <i>evidence</i>.</li>
<li><b>Retención:</b> grabaciones 30 días (UK GDPR); Log Analytics 30 días.</li></ul></div>
</div>

<div class="sep"><b>Aislamiento (restricción 2):</b><span class="pill">El camino caliente solo recibe el modelo aprobado</span>→<span class="pill2">JSON + SHA-256 dentro de su imagen</span>
<span>|</span><span class="pill">El batch solo recibe eventos</span>→<span class="pill2">cola de una vía, sin audio</span><span>|</span><span class="pill2">VNets sin peering · imágenes, identidades y permisos separados</span></div>
<div class="ver">Trazabilidad: {VERIFIED}/{len(RESULTS)} afirmaciones de este diagrama y de los C4 verificadas automáticamente contra el código (<code>tools/architecture_claims.py</code>, <code>docs/TRAZABILIDAD.md</code>).</div>
</body></html>"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / "src" / "Pipeline_MLOps_Inferencia.html"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(html(), encoding="utf-8")
    import subprocess

    js = (
        "const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();"
        "const p=await b.newPage({viewport:{width:2400,height:1000},deviceScaleFactor:2});"
        "await p.goto(process.argv[1]);await p.screenshot({path:process.argv[2],fullPage:true});await b.close();})();"
    )
    subprocess.run(["node", "-e", js, src.as_uri(), str(OUT / "Pipeline_MLOps_Inferencia.png")], check=True)
    print(OUT / "Pipeline_MLOps_Inferencia.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
