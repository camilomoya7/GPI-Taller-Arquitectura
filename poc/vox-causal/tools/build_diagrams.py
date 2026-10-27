"""Genera los diagramas C4 (Graphviz) con cifras leídas de los resultados medidos.

Las cifras (latencia, error de ATE, calibración) y los parámetros (sesiones, ventana, TTL de SAS)
se leen del código y de los archivos de resultados, nunca se escriben a mano.

Salida: docs/diagrams/src/*.dot y docs/diagrams/*.png   (requiere Graphviz: dot)
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "diagrams" / "src"
PNG = ROOT / "docs" / "diagrams"

_spec = importlib.util.spec_from_file_location("architecture_claims", ROOT / "tools" / "architecture_claims.py")
claims = importlib.util.module_from_spec(_spec)
sys.modules["architecture_claims"] = claims
_spec.loader.exec_module(claims)
M = claims.measured()
S = claims._settings()

FONT = "Inter"


def es(x: float, nd: int = 4) -> str:
    """Número con coma decimal (formato del informe)."""
    return f"{x:.{nd}f}".replace(".", ",")
C = {  # paleta de la Parte 1
    "person": ("#0b4a63", "#ffffff"), "focus": ("#c2349b", "#ffffff"), "ext": ("#8a8a8a", "#ffffff"),
    "opt": ("#14b29f", "#ffffff"), "comp": ("#1f6fb2", "#ffffff"), "data": ("#e9eef3", "#1b2b38"),
    "planned": ("#ffffff", "#333333"), "gate": ("#f2a900", "#1b1b1b"),
}


def lbl(title: str, *lines: str, size: int = 13) -> str:
    body = "".join(f'<BR/><FONT POINT-SIZE="{size}">{escape(x)}</FONT>' for x in lines)
    return f"<<B>{escape(title)}</B>{body}>"


def node(name: str, kind: str, title: str, *lines: str, shape: str = "box", extra: str = "") -> str:
    fill, font = C[kind]
    style = "rounded,filled"
    pen = "1.2"
    color = fill
    if kind == "planned":
        style, color = "rounded,dashed,filled", "#7a7a7a"
    if kind == "data":
        color = "#46617a"
    if kind == "focus":
        color, pen = "#8e1f70", "2.5"
    if shape == "cylinder":
        style = "filled"
    return (f'  {name} [shape={shape}, style="{style}", fillcolor="{fill}", fontcolor="{font}", '
            f'color="{color}", penwidth={pen}, label={lbl(title, *lines)} {extra}];\n')


def edge(a: str, b: str, text: str = "", style: str = "solid", extra: str = "") -> str:
    lab = f', label=<{escape(text).replace(chr(10), "<BR/>")}>' if text else ""
    return f'  {a} -> {b} [style={style}{lab} {extra}];\n'


def header(title: str, rankdir: str = "TB", nodesep: float = 0.6, ranksep: float = 0.9, splines: str = "spline") -> str:
    return f"""digraph G {{
  graph [fontname="{FONT}", rankdir={rankdir}, splines={splines}, nodesep={nodesep}, ranksep={ranksep},
         pad=0.4, label=<<B>{escape(title)}</B>>, labelloc=t, fontsize=26, bgcolor="white", newrank=true,
         compound=true];
  node [fontname="{FONT}", fontsize=15, margin="0.22,0.12"];
  edge [fontname="{FONT}", fontsize=12, color="#555555", fontcolor="#2b2b2b", arrowsize=0.8, penwidth=1.2];
"""


def legend(*items: tuple[str, str]) -> str:
    out = ['  subgraph cluster_legend { label=<<B>Leyenda</B>>; fontsize=14; color="#bbbbbb"; style="rounded";\n']
    for i, (text, kind) in enumerate(items):
        fill, font = C[kind]
        style = "rounded,dashed,filled" if kind == "planned" else "rounded,filled"
        out.append(f'    lg{i} [shape=box, style="{style}", fillcolor="{fill}", fontcolor="{font}", color="#888888", '
                   f'fontsize=12, label="{text}"];\n')
    out.append("    " + " -> ".join(f"lg{i}" for i in range(len(items))) + " [style=invis];\n  }\n")
    return "".join(out)


# ──────────────────────────────── Nivel 1 ────────────────────────────────
def n1() -> str:
    d = header("C4 Nivel 1 — Contexto — Vox-Causal AI (Alloxentric SpA)", "TB", 0.7, 1.0)
    d += node("cliente", "person", "Cliente que llama", "Su voz se analiza para detectar estrés", "Se le informa al inicio de la llamada")
    d += node("operador", "person", "Operador del contact center", "Recibe causa raíz y acción sugerida", "Su voz NO se analiza (EU AI Act)")
    d += node("supervisor", "person", "Supervisor de calidad", "Revisa explicaciones post-llamada", "Escucha grabaciones con SAS")
    d += node("mlops", "person", "Equipo Data Science / MLOps", "Entrena, aprueba y promueve", "modelos causales")
    d += node("tel", "ext", "Plataforma de telefonía (CCaaS)", "Sistema existente de Alloxentric", "Audio de la llamada y eventos de", "contexto: espera, transferencias")
    d += node("crm", "ext", "Consola del operador / CRM", "Plataforma SaaS de Alloxentric", "Contexto del cliente: facturación,", "antigüedad, contacto repetido")
    d += node("vox", "focus", "Vox-Causal AI", "Motor de inferencia causal y análisis", "prosódico en tiempo real",
              "Python 3.12 · FastAPI · DoWhy / EconML", "Azure UK South", "[SISTEMA EN FOCO]")
    d += node("aoai", "opt", "Azure OpenAI", "Redacta la explicación post-llamada", "Opcional: sin acceso → plantilla", "NO decide la causa raíz")
    d += node("entra", "ext", "Microsoft Entra ID", "Identidades administradas", "Firma de SAS de delegación")
    d += node("mon", "ext", "Azure Monitor · Log Analytics", "Telemetría, latencia y auditoría")
    d += "  { rank=same; cliente; operador; supervisor; mlops; }\n  { rank=same; tel; crm; }\n  { rank=same; aoai; entra; mon; }\n"
    d += edge("cliente", "tel", "Habla durante\nla llamada")
    d += edge("operador", "tel", "Atiende\nla llamada")
    d += edge("tel", "vox", "Audio PCM16 del canal cliente\n+ eventos de contexto\nWSS · TLS 1.2+")
    d += edge("crm", "vox", "Contexto del cliente\nWSS · JSON")
    d += edge("vox", "crm", f"Causa raíz, riesgo y acción\ncada {S.hop_ms} ms · WSS · JSON", extra=", constraint=false")
    d += edge("crm", "operador", "Muestra el diagnóstico\nen vivo", extra=", constraint=false")
    d += edge("supervisor", "vox", f"Lee explicaciones; pide grabaciones\nHTTPS · SAS solo lectura {S.sas_ttl_minutes} min")
    d += edge("mlops", "vox", "Entrena, aprueba y promueve\nGit · CI/CD")
    d += edge("vox", "aoai", "Solicita redacción\nHTTPS · identidad administrada")
    d += edge("vox", "entra", "Tokens OAuth 2.0 y\nclaves de delegación")
    d += edge("vox", "mon", "Logs JSON, métricas\ny auditoría")
    d += legend(("Persona", "person"), ("Sistema en foco", "focus"), ("Sistema externo", "ext"), ("Servicio externo opcional", "opt"))
    return d + "}\n"


# ──────────────────────────────── Nivel 2 ────────────────────────────────
def n2() -> str:
    d = header("C4 Nivel 2 — Contenedores — Vox-Causal AI · dos zonas aisladas (restricción 2)", "TB", 0.55, 0.85)
    d += node("tel", "ext", "Plataforma de telefonía", "CCaaS de Alloxentric")
    d += node("crm", "ext", "Consola del operador / CRM", "Plataforma SaaS de Alloxentric")
    d += node("sup", "person", "Supervisor de calidad")
    d += node("dev", "person", "Equipo MLOps")
    d += '  subgraph cluster_za { label=<<B>ZONA A · TIEMPO REAL</B><BR/><FONT POINT-SIZE="12">vnet-rt 10.10.0.0/16 · Container Apps cae-rt · ingreso público solo HTTPS/WSS</FONT>>; style="rounded,filled"; fillcolor="#fdf2fa"; color="#c2349b"; penwidth=2; fontsize=16;\n'
    d += node("apim", "planned", "Azure API Management", "Gateway WSS · cuotas · autenticación", "[Diseño productivo: nivel Developer+]")
    d += node("api", "focus", "API de inferencia", "FastAPI · Python 3.12 · NumPy", "1 vCPU / 2 GiB por réplica · réplicas 1–10",
              f"admisión {S.max_sessions} sesiones por réplica", f"p95 {M['p95_180']:.0f} ms con {S.max_sessions} llamadas",
              "modelo aprobado dentro de la imagen")
    d += "    { rank=same; apim; api; }\n  }\n"
    d += '  subgraph cluster_fr { label=<<B>FRONTERA · UNA SOLA VÍA</B>>; style="rounded,filled"; fillcolor="#fff8e6"; color="#d49a00"; fontsize=15;\n'
    d += node("sb", "data", "Azure Service Bus", "cola call-closed · nivel Basic", "solo Entra ID (sin claves)", "API = Sender · batch = Receiver", shape="cylinder")
    d += "  }\n"
    d += '  subgraph cluster_zb { label=<<B>ZONA B · BATCH</B><BR/><FONT POINT-SIZE="12">vnet-batch 10.20.0.0/16 · Container Apps cae-batch · SIN ingreso público · sin peering con zona A</FONT>>; style="rounded,filled"; fillcolor="#eef7f1"; color="#2e8b57"; penwidth=2; fontsize=16;\n'
    d += node("worker", "focus", "Worker post-llamada", "Container Apps Job · Python 3.12", "explicación + auditoría")
    d += node("train", "focus", "Pipeline de entrenamiento causal", "Container Apps Job · 2 vCPU", "DoWhy + EconML · refutación",
              "control de calidad: error ATE ≤ 0,05")
    d += "    { rank=same; worker; train; }\n  }\n"
    d += '  subgraph cluster_data { label=<<B>DATOS · Azure Blob Storage UK South</B><BR/><FONT POINT-SIZE="12">TLS ≥ 1.2 · solo HTTPS · sin claves compartidas · sin acceso público</FONT>>; style="rounded,filled"; fillcolor="#f1f5f9"; color="#46617a"; fontsize=15;\n'
    d += node("rec", "data", "recordings", "grabaciones · retención 30 días", "acceso por User Delegation SAS", shape="cylinder")
    d += node("aud", "data", "audit", "explicaciones y auditoría", shape="cylinder")
    d += node("reg", "data", "model-registry", "versiones + SHA-256 + métricas", shape="cylinder")
    d += "    { rank=same; rec; aud; reg; }\n  }\n"
    d += node("aoai", "opt", "Azure OpenAI", "[Opcional · respaldo por plantilla]")
    d += ('  tr [shape=box, style="rounded,filled", fillcolor="#f7f7f7", color="#999999", fontcolor="#222222", '
          'label=<<B>TRANSVERSAL (ambas zonas, identidades separadas)</B><BR/><FONT POINT-SIZE="12">'
          'Key Vault (RBAC): token API y clave de seudónimos · Container Registry sin usuario admin: 2 imágenes<BR/>'
          'Log Analytics: logs JSON y métricas · 3 identidades administradas (api, batch, test) con mínimo privilegio<BR/>'
          '<I>Private Endpoints: diseño productivo</I></FONT>>];\n')
    d += "  { rank=same; tel; crm; sup; dev; }\n"
    d += edge("tel", "apim", "Audio PCM16 + contexto\nWSS · TLS 1.2+")
    d += edge("apim", "api", "WSS", "dashed")
    d += edge("tel", "api", "PoC: ingreso HTTPS/WSS\nde Container Apps", "dotted")
    d += edge("api", "crm", "Diagnóstico en vivo\nWSS · JSON")
    d += edge("sup", "api", "POST /v1/recordings/…/access\nHTTPS")
    d += edge("api", "sb", "call.closed (sin audio, seudónimo)\nAMQP · TLS · no bloqueante")
    d += edge("sb", "worker", "AMQP · TLS")
    d += edge("worker", "aud", "HTTPS · escribe")
    d += edge("worker", "aoai", "HTTPS · identidad\nadministrada")
    d += edge("train", "reg", "Publica versión\naprobada · HTTPS")
    d += edge("api", "rec", f"Emite SAS: solo lectura\nspr=https · {S.sas_ttl_minutes} min", "dashed")
    d += edge("reg", "dev", "Promoción: verifica SHA-256\n→ commit → CI → imagen nueva", "dashed", extra=", constraint=false")
    d += edge("dev", "api", "Despliega revisión inmutable")
    d += edge("aoai", "tr", "", "invis")
    d += legend(("Persona", "person"), ("Sistema externo", "ext"), ("Contenedor implementado", "focus"),
                ("Almacén de datos", "data"), ("Diseño productivo (no en la PoC)", "planned"), ("Servicio opcional", "opt"))
    return d + "}\n"


# ──────────────────────────────── Nivel 3 · API ────────────────────────────────
def n3_api() -> str:
    d = header("C4 Nivel 3 — Componentes — API de inferencia (camino caliente < 200 ms)", "TB", 0.5, 0.75)
    d += node("tel", "ext", "Plataforma de telefonía", "WSS: start · audio PCM16 · context · stop")
    d += node("sup", "person", "Supervisor")
    d += node("crm", "ext", "Consola del operador")
    d += '  subgraph cluster_c { label=<<B>Contenedor: API de inferencia</B><BR/><FONT POINT-SIZE="12">FastAPI · uvicorn · Python 3.12 · 1 vCPU · sin DoWhy/EconML/pandas</FONT>>; style="rounded,filled"; fillcolor="#f4f8fc"; color="#1f6fb2"; penwidth=2; fontsize=16;\n'
    d += node("borde", "comp", "1 · Borde WebSocket / REST", "main.py · ws_handler.py", "token Bearer en tiempo constante",
              f"admisión {S.max_sessions} sesiones · cierres 1008 / 1013")
    d += node("priv", "comp", "2 · Política de privacidad", "privacy.py", "solo canal cliente (EU AI Act 5.1.f)", "seudónimo HMAC-SHA256")
    d += node("sess", "comp", "3 · Sesión de streaming", "stream.py", "descarta el canal del operador",
              f"ventana {S.window_ms} ms cada {S.hop_ms} ms · coalescencia")
    d += node("feat", "opt", "4 · Extractor prosódico", "libs/voxfeatures (compartida con batch)", f"7 rasgos · p95 {es(M['stages']['prosody']['p95_ms'], 2)} ms por ventana")
    d += node("scm", "comp", "5 · Runtime causal", "scm_runtime.py · solo NumPy", "estrés · riesgo · causa raíz por ATE",
              f"estrés no explicado · p95 {es(M['stages']['scm']['p95_ms'], 2)} ms")
    d += node("store", "comp", "6 · Almacén del modelo", "model_store.py", "verifica SHA-256 y esquema", "modo estricto / degradado")
    d += node("pub", "comp", "7 · Publicador de eventos", "events.py", "no bloqueante · timeout 3 s", "outbox de respaldo")
    d += node("sas", "comp", "8 · Emisor de SAS", "sas.py · User Delegation", f"solo lectura · spr=https · {S.sas_ttl_minutes} min",
              "clave de delegación en caché")
    d += node("tlm", "comp", "9 · Telemetría y auditoría", "telemetry.py", "p50 / p95 / p99 por etapa",
              "model_loaded · sas_issued · channel_rejected")
    d += "    { rank=same; priv; sess; }\n    { rank=same; feat; scm; store; }\n    { rank=same; pub; sas; tlm; }\n"
    d += "  }\n"
    d += node("model", "data", "model.json + SHA-256", "dentro de la imagen", "único contrato con el batch", shape="cylinder")
    d += node("sb", "data", "Service Bus", "cola call-closed", shape="cylinder")
    d += node("blob", "data", "Blob recordings", shape="cylinder")
    d += node("entra", "ext", "Microsoft Entra ID")
    d += node("law", "ext", "Log Analytics")
    d += "  { rank=same; tel; sup; crm; }\n  { rank=same; sb; blob; entra; law; }\n"
    d += edge("tel", "borde", "WSS · TLS 1.2+")
    d += edge("sup", "borde", "HTTPS")
    d += edge("borde", "crm", f"inference JSON\ncada {S.hop_ms} ms", extra=", constraint=false")
    d += edge("borde", "priv", "start")
    d += edge("priv", "sess", "canal válido")
    d += edge("sess", "feat", "ventana de audio")
    d += edge("feat", "scm", "rasgos")
    d += edge("scm", "store", "efectos causales\ny pesos", extra=", dir=back")
    d += edge("model", "store", "carga al iniciar", extra=", constraint=false")
    d += edge("scm", "borde", "diagnóstico", extra=", constraint=false")
    d += edge("borde", "pub", "al cerrar la sesión")
    d += edge("borde", "sas", "acceso a grabación")
    d += edge("borde", "tlm", "tiempos por etapa", "dotted")
    d += edge("pub", "sb", "AMQP · TLS · Sender")
    d += edge("sas", "entra", "clave de delegación")
    d += edge("sas", "blob", "URL firmada", "dashed")
    d += edge("tlm", "law", "stdout JSON")
    d += edge("scm", "pub", "", "invis")
    d += edge("store", "model", "", "invis")
    d += legend(("Componente", "comp"), ("Librería compartida", "opt"), ("Externo al contenedor", "ext"), ("Almacén / artefacto", "data"))
    return d + "}\n"


# ──────────────────────────────── Nivel 3 · Batch ────────────────────────────────
def n3_batch() -> str:
    errs = " · ".join(es(v) for v in M["ate_error_dml"].values())
    d = header("C4 Nivel 3 — Componentes — Pipeline batch (camino frío)", "TB", 0.5, 0.7)
    d += node("sb", "data", "Service Bus", "cola call-closed", shape="cylinder")
    d += '  subgraph cluster_c { label=<<B>Contenedor: Pipeline batch</B><BR/><FONT POINT-SIZE="12">Container Apps Jobs · Python 3.12 · DoWhy · EconML · zona B sin ingreso público</FONT>>; style="rounded,filled"; fillcolor="#f3faf5"; color="#2e8b57"; penwidth=2; fontsize=16;\n'
    d += node("entry", "comp", "1 · Punto de entrada", "entry.py · JOB_MODE", "worker · train · bench")
    d += '    subgraph cluster_train { label=<<B>Entrenamiento causal (JOB_MODE=train)</B>>; style="rounded"; color="#7fb89a"; fontsize=13;\n'
    d += node("syn", "comp", "2 · Generador SCM", "synthetic.py", "3 causas · 3 confusores · mediador", "ATE verdadero por do(T)")
    d += node("est", "comp", "3 · Identificación y estimación", "train.py · DoWhy (backdoor)", "EconML LinearDML")
    d += node("ref", "comp", "4 · Refutación", "placebo · causa común aleatoria", "subconjunto 80 %")
    d += node("feat", "opt", "libs/voxfeatures", "misma librería que la API")
    d += node("cal", "comp", "5 · Calibración prosódica", "voz sintética etiquetada", f"MAE {es(M['stress_mae'], 3)} · R² {es(M['stress_r2'], 3)}")
    d += node("gate", "gate", "6 · Control de calidad", "error ATE ≤ 0,05 y refutaciones OK", f"medido: {errs}", shape="hexagon")
    d += node("regc", "comp", "7 · Registro de modelos", "registry.py", "versión + SHA-256 + métricas")
    d += node("rej", "data", "rejected/", "no se publica", shape="cylinder")
    d += "      { rank=same; syn; feat; }\n      { rank=same; est; cal; }\n      { rank=same; regc; rej; }\n"
    d += "    }\n"
    d += '    subgraph cluster_wrk { label=<<B>Post-llamada (JOB_MODE=worker)</B>>; style="rounded"; color="#7fb89a"; fontsize=13;\n'
    d += node("wk", "comp", "8 · Worker", "worker.py", "consume eventos · escribe auditoría")
    d += node("ex", "comp", "9 · Explicador", "explain.py", "Azure OpenAI o plantilla")
    d += "    }\n  }\n"
    d += node("aoai", "opt", "Azure OpenAI", "[opcional]")
    d += node("aud", "data", "Blob audit", shape="cylinder")
    d += node("reg", "data", "Blob model-registry", shape="cylinder")
    d += node("promote", "comp", "10 · Promoción", "promote_model.py", "verifica SHA-256")
    d += node("ci", "ext", "Git + CI", "lint · pruebas · cobertura ≥ 85 %", "construcción de imágenes")
    d += node("apiimg", "ext", "Imagen de la API", "(zona A)")
    d += "  { rank=same; reg; promote; ci; apiimg; }\n  { rank=same; aoai; aud; }\n"
    d += edge("entry", "syn")
    d += edge("entry", "wk")
    d += edge("syn", "est", "datos con efecto conocido")
    d += edge("est", "ref", "estimación")
    d += edge("ref", "gate")
    d += edge("feat", "cal", "rasgos")
    d += edge("cal", "gate")
    d += edge("gate", "regc", "aprueba")
    d += edge("gate", "rej", "rechaza")
    d += edge("sb", "wk", "AMQP · TLS · Receiver")
    d += edge("wk", "ex", "evento")
    d += edge("ex", "aoai", "HTTPS · identidad\nadministrada")
    d += edge("wk", "aud", "HTTPS")
    d += edge("regc", "reg", "HTTPS")
    d += edge("reg", "promote")
    d += edge("promote", "ci", "commit")
    d += edge("ci", "apiimg", "imagen inmutable")
    d += legend(("Componente", "comp"), ("Control de calidad", "gate"), ("Librería compartida", "opt"),
                ("Externo", "ext"), ("Almacén / artefacto", "data"))
    return d + "}\n"


def main() -> int:
    SRC.mkdir(parents=True, exist_ok=True)
    for name, fn in (("C4_N1_Contexto", n1), ("C4_N2_Contenedores", n2),
                     ("C4_N3_Componentes_API", n3_api), ("C4_N3_Componentes_Batch", n3_batch)):
        dot = SRC / f"{name}.dot"
        dot.write_text(fn(), encoding="utf-8")
        subprocess.run(["dot", "-Tpng", "-Gdpi=220", str(dot), "-o", str(PNG / f"{name}.png")], check=True)
        print(PNG / f"{name}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
