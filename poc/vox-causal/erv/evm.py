"""Gestión del Valor Ganado (EVM) del proyecto de integración de Vox-Causal AI.

Línea base: 800 horas-hombre (CAPEX del caso) distribuidas en una EDT de 7 paquetes y 12 semanas.
Fecha de corte: fin de la semana 6 (la restricción del cliente se inyectó en la semana 5).

Origen de los datos (declarado en el informe):
  * PV: línea base planificada (este archivo).
  * EV: % de avance físico de cada paquete, estimado a partir de entregables verificables del
    repositorio (código, pruebas, scripts y diagramas existentes).
  * AC: horas reales SIMULADAS para el ejercicio académico (incluyen el retrabajo por el incidente).

Salida: erv/out/evm.json, erv/out/evm_curva_s.png, erv/out/evm_cuadrante.png
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
WEEKS = 12
STATUS_WEEK = 6
INCIDENT_WEEK = 5
RATE_GBP_H = 575 / 7.5          # tarifa mediana UK de contratos de ML (£575/día, IT Jobs Watch, oct-2026)
RESERVE_PCT = 0.10              # reserva de contingencia sobre el BAC

# Paleta de referencia validada (slots 1-3 aprobados en todos los pares, modo claro)
C_PV, C_EV, C_AC = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"


@dataclass
class WorkPackage:
    code: str
    name: str
    hours: float
    start: int          # semana de inicio (1..12)
    end: int            # semana de término
    pct_complete: float  # avance físico a la fecha de corte (0..1)
    actual_hours: float  # AC simulado a la fecha de corte
    evidence: str
    r: str              # Responsable (RACI)


WBS = [
    WorkPackage("1", "Gestión del proyecto, gobernanza y DPIA", 60, 1, 12, 0.50, 33,
                "README, RACI, informe ERV en curso", "Ignacio Ortega"),
    WorkPackage("2", "Refactorización del prototipo en dos servicios", 160, 1, 4, 1.00, 168,
                "services/inference_api y services/batch_pipeline", "Camilo Moya"),
    WorkPackage("3", "Integración Azure (APIM, Service Bus, Blob SAS, Entra ID, Key Vault)", 140, 3, 8, 0.55, 93,
                "deploy.sh y verify.sh validados; despliegue pendiente", "Lucas Mora"),
    WorkPackage("4", "Pipeline MLOps (DoWhy/EconML, refutación, registro, CI)", 140, 3, 7, 0.90, 131,
                "pipeline/train.py, registry.py, ci/vox-causal-ci.yml", "Joaquín Apablaza"),
    WorkPackage("5", "Seguridad y cumplimiento (TLS, SAS, aislamiento, UK GDPR)", 90, 5, 9, 0.60, 66,
                "sas.py, privacy.py, pruebas de arquitectura", "Lucas Mora"),
    WorkPackage("6", "Pruebas SQA y desempeño (latencia, concurrencia, ATE)", 130, 6, 10, 0.40, 55,
                "114 pruebas, 96 % cobertura, benchmark local", "Joaquín Apablaza"),
    WorkPackage("7", "Piloto productivo y transferencia", 80, 10, 12, 0.00, 0,
                "pendiente", "Ignacio Ortega"),
]


def weekly_plan(wp: WorkPackage) -> list[float]:
    span = wp.end - wp.start + 1
    return [wp.hours / span if wp.start <= w <= wp.end else 0.0 for w in range(1, WEEKS + 1)]


def weekly_actuals(wp: WorkPackage) -> tuple[list[float], list[float]]:
    """EV y AC semanales hasta la fecha de corte.

    EV: el avance se reparte uniformemente entre las semanas efectivamente trabajadas
    (el paquete 6 se adelantó a la semana 4 porque las pruebas se escribieron junto al código).
    AC: hasta la semana 4 se gasta ~2 % sobre el valor ganado; el resto del AC (retrabajo
    por las restricciones inyectadas en la semana 5) cae en las semanas 5 y 6.
    """
    start = 4 if wp.code == "6" else wp.start
    worked = [w for w in range(start, STATUS_WEEK + 1) if w <= wp.end or wp.pct_complete < 1]
    worked = [w for w in worked if w >= start]
    ev_total = wp.hours * wp.pct_complete
    ev = [0.0] * WEEKS
    if worked and ev_total:
        for w in worked:
            ev[w - 1] = ev_total / len(worked)
    ac = [0.0] * WEEKS
    pre = [w for w in worked if w < INCIDENT_WEEK]
    post = [w for w in worked if w >= INCIDENT_WEEK]
    for w in pre:
        ac[w - 1] = ev[w - 1] * 1.02
    remaining = wp.actual_hours - sum(ac)
    if post:
        ev_post = sum(ev[w - 1] for w in post) or len(post)
        for w in post:
            ac[w - 1] = remaining * ((ev[w - 1] or 1) / ev_post)
    elif pre:
        scale = wp.actual_hours / sum(ac)
        ac = [v * scale for v in ac]
    return ev, ac


def cumulative(xs: list[float]) -> list[float]:
    out, s = [], 0.0
    for x in xs:
        s += x
        out.append(s)
    return out


def compute() -> dict:
    bac = sum(wp.hours for wp in WBS)
    pv_w = [sum(weekly_plan(wp)[i] for wp in WBS) for i in range(WEEKS)]
    ev_w = [0.0] * WEEKS
    ac_w = [0.0] * WEEKS
    rows = []
    for wp in WBS:
        ev, ac = weekly_actuals(wp)
        ev_w = [a + b for a, b in zip(ev_w, ev, strict=True)]
        ac_w = [a + b for a, b in zip(ac_w, ac, strict=True)]
        pv_t = sum(weekly_plan(wp)[:STATUS_WEEK])
        ev_t = wp.hours * wp.pct_complete
        rows.append({
            "code": wp.code, "name": wp.name, "bac_h": wp.hours, "weeks": f"S{wp.start}–S{wp.end}",
            "pv_h": round(pv_t, 1), "ev_h": round(ev_t, 1), "ac_h": round(wp.actual_hours, 1),
            "pct_complete": wp.pct_complete,
            "spi": round(ev_t / pv_t, 2) if pv_t else None,
            "cpi": round(ev_t / wp.actual_hours, 2) if wp.actual_hours else None,
            "evidence": wp.evidence, "responsable": wp.r,
        })
    pv_c, ev_c, ac_c = cumulative(pv_w), cumulative(ev_w), cumulative(ac_w)
    pv, ev, ac = pv_c[STATUS_WEEK - 1], ev_c[STATUS_WEEK - 1], ac_c[STATUS_WEEK - 1]
    spi, cpi = ev / pv, ev / ac
    eac = bac / cpi
    etc = eac - ac
    tcpi = (bac - ev) / (bac - ac)
    weekly = []
    for i in range(STATUS_WEEK):
        weekly.append({"week": i + 1, "pv_pct": pv_c[i] / bac * 100, "ev_pct": ev_c[i] / bac * 100,
                       "ac_pct": ac_c[i] / bac * 100,
                       "spi": ev_c[i] / pv_c[i], "cpi": ev_c[i] / ac_c[i]})
    reserve_h = bac * RESERVE_PCT
    return {
        "bac_h": bac, "rate_gbp_h": round(RATE_GBP_H, 2), "bac_gbp": round(bac * RATE_GBP_H, 2),
        "status_week": STATUS_WEEK, "incident_week": INCIDENT_WEEK, "weeks": WEEKS,
        "pv_h": round(pv, 1), "ev_h": round(ev, 1), "ac_h": round(ac, 1),
        "pv_pct": round(pv / bac * 100, 1), "ev_pct": round(ev / bac * 100, 1), "ac_pct": round(ac / bac * 100, 1),
        "sv_h": round(ev - pv, 1), "cv_h": round(ev - ac, 1),
        "spi": round(spi, 3), "cpi": round(cpi, 3),
        "eac_h": round(eac, 1), "etc_h": round(etc, 1), "vac_h": round(bac - eac, 1),
        "tcpi": round(tcpi, 3),
        "eac_gbp": round(eac * RATE_GBP_H, 2), "vac_gbp": round((bac - eac) * RATE_GBP_H, 2),
        "classification": classify(cpi, spi)[0],
        "reserve_h": reserve_h, "reserve_covers_overrun": (eac - bac) <= reserve_h,
        "reserve_consumed_pct": round((eac - bac) / reserve_h * 100, 1),
        "pv_curve_pct": [round(x / bac * 100, 2) for x in pv_c],
        "ev_curve_pct": [round(x / bac * 100, 2) for x in ev_c[:STATUS_WEEK]],
        "ac_curve_pct": [round(x / bac * 100, 2) for x in ac_c[:STATUS_WEEK]],
        "weekly": [{k: round(v, 3) if isinstance(v, float) else v for k, v in w.items()} for w in weekly],
        "packages": rows,
    }


def _style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=10)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def chart_s_curve(r: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=200)
    _style(ax)
    weeks = list(range(1, r["weeks"] + 1))
    st = r["status_week"]
    # pronóstico: EV sigue el plan restante; AC al ritmo del CPI
    fc_weeks = list(range(st, r["weeks"] + 1))
    remaining_pv = [p - r["pv_curve_pct"][st - 1] for p in r["pv_curve_pct"][st - 1:]]
    span = 100 - r["ev_pct"]
    rem_plan = 100 - r["pv_curve_pct"][st - 1]
    ev_fc = [r["ev_pct"] + span * (x / rem_plan) for x in remaining_pv]
    ac_fc = [r["ac_pct"] + (e - r["ev_pct"]) / r["cpi"] for e in ev_fc]
    ax.plot(weeks, r["pv_curve_pct"], color=C_PV, lw=2, label="PV · valor planificado")
    ax.plot(weeks[:st], r["ev_curve_pct"], color=C_EV, lw=2, marker="o", ms=5, label="EV · valor ganado")
    ax.plot(weeks[:st], r["ac_curve_pct"], color=C_AC, lw=2, marker="s", ms=5, label="AC · costo real")
    ax.plot(fc_weeks, ev_fc, color=C_EV, lw=1.6, ls="--")
    ax.plot(fc_weeks, ac_fc, color=C_AC, lw=1.6, ls="--", label=f"Pronóstico (EAC = {r['eac_h']/r['bac_h']*100:.0f} % del BAC)")
    ax.axvline(st, color=INK2, lw=1, ls=":")
    ax.text(st + 0.1, 4, f"Corte: semana {st}", color=INK2, fontsize=9)
    ax.axvspan(r["incident_week"] - 0.5, r["incident_week"] + 0.5, color="#f2a900", alpha=0.12)
    ax.text(r["incident_week"] - 0.45, 96, "Incidente\n(restricciones)", color=INK2, fontsize=8.5, va="top")
    ax.axhline(100, color=INK2, lw=0.8)
    ax.text(r["weeks"] + 0.4, 101.5, f"BAC = {r['bac_h']} h", color=INK2, fontsize=9, ha="right")
    for y in (r["ev_pct"], r["ac_pct"], r["pv_pct"]):
        ax.annotate(f"{y:.1f} %".replace(".", ","), (st, y), xytext=(6, 0), textcoords="offset points",
                    color=INK, fontsize=9, va="center", fontweight="bold")
    ax.set_xlim(0.5, r["weeks"] + 0.5)
    ax.set_ylim(0, 118)
    ax.set_xticks(weeks)
    ax.set_xlabel("Semana del proyecto", color=INK2)
    ax.set_ylabel("% acumulado del presupuesto (BAC)", color=INK2)
    ax.set_title("Curva S — PV, EV y AC acumulados (%)", color=INK, fontsize=13, loc="left", fontweight="bold")
    ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURF)
    plt.close(fig)


# Cuadrante de desempeño con el formato de la cátedra: celdas coloreadas según el menor de CPI y SPI.
CLASSES = [  # (umbral mínimo, estado, color)
    (1.15, "Excepcional", "#B4A7D6"),
    (1.10, "Muy Bueno", "#A4C2F4"),
    (1.00, "Satisfactorio", "#B6D7A8"),
    (0.90, "Marginal", "#FFE599"),
    (-1.0, "No Satisfactorio", "#EA9999"),
]
SPI_TICKS = [0.75, 0.8, 0.84, 0.86, 0.88, 0.9, 0.92, 0.94, 0.96, 0.98, 1.0, 1.02, 1.04, 1.06, 1.08,
             1.1, 1.12, 1.14, 1.15, 1.18]
CPI_TICKS = [round(0.45 + 0.05 * i, 2) for i in range(21)]  # 0,45 … 1,45


def classify(cpi: float, spi: float) -> tuple[str, str]:
    m = min(cpi, spi)
    for thr, name, color in CLASSES:
        if m >= thr - 1e-9:
            return name, color
    return CLASSES[-1][1], CLASSES[-1][2]


def _pos(value: float, ticks: list[float]) -> float:
    """Posición (en índice de celda) de un valor sobre un eje categórico no uniforme."""
    if value <= ticks[0]:
        return 0.0
    if value >= ticks[-1]:
        return float(len(ticks) - 1)
    for i in range(len(ticks) - 1):
        if ticks[i] <= value <= ticks[i + 1]:
            return i + (value - ticks[i]) / (ticks[i + 1] - ticks[i])
    return 0.0


def _fmt(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def chart_quadrant(r: dict, path: Path) -> None:
    from matplotlib.patches import FancyBboxPatch, Rectangle

    nx, ny = len(SPI_TICKS), len(CPI_TICKS)
    fig = plt.figure(figsize=(12.5, 6.6), dpi=200)
    ax = fig.add_axes([0.06, 0.10, 0.56, 0.74])
    ax.set_xlim(-0.5, nx - 0.5)
    ax.set_ylim(-0.5, ny - 0.5)
    for i, spi in enumerate(SPI_TICKS):
        for j, cpi in enumerate(CPI_TICKS):
            ax.add_patch(Rectangle((i - 0.5, j - 0.5), 1, 1, facecolor=classify(cpi, spi)[1],
                                   edgecolor="white", linewidth=1.2))
    x1, y1 = SPI_TICKS.index(1.0), CPI_TICKS.index(1.0)
    for txt, (x, y) in {"I": (nx * 0.78, ny * 0.80), "II": (nx * 0.22, ny * 0.80),
                        "III": (nx * 0.22, ny * 0.22), "IV": (nx * 0.78, ny * 0.22)}.items():
        ax.text(x, y, txt, ha="center", va="center", fontsize=16, color="#555555", fontweight="bold",
                family="serif")
    ax.axvline(x1 - 0.5, color="#555555", lw=0.6, alpha=0.5)
    ax.axhline(y1 - 0.5, color="#555555", lw=0.6, alpha=0.5)
    ax.set_xticks(range(nx))
    ax.set_xticklabels([f"{t:g}".replace(".", ",") for t in SPI_TICKS], fontsize=8.5, fontweight="bold")
    ax.set_yticks(range(ny))
    ax.set_yticklabels([f"{t:g}".replace(".", ",") for t in CPI_TICKS], fontsize=8.5, fontweight="bold")
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.text(nx - 0.2, -1.25, "SPI", fontsize=11, fontweight="bold", ha="left", va="center")
    ax.text(-1.6, ny - 0.35, "CPI", fontsize=11, fontweight="bold", ha="left", va="bottom")
    fig.text(0.06, 0.955, "Indicadores de Desempeño del Proyecto (EVM)", fontsize=15, fontweight="bold", family="serif")
    fig.text(0.06, 0.915, "Cuadrante de Desempeño (CPI vs SPI) — el punto negro marca la posición actual",
             fontsize=10.5, fontweight="bold", family="serif")

    # trayectoria semanal (gris) y posición al corte (punto negro)
    pts = [(_pos(w["spi"], SPI_TICKS), _pos(w["cpi"], CPI_TICKS)) for w in r["weekly"]]
    ax.plot([p[0] for p in pts], [p[1] for p in pts], color="#444444", lw=1, ls="--", alpha=0.7, zorder=3)
    ax.scatter([p[0] for p in pts[:-1]], [p[1] for p in pts[:-1]], s=18, color="#777777", zorder=4)
    ax.scatter([pts[-1][0]], [pts[-1][1]], s=150, color="black", zorder=5)
    lines = [f"S{w['week']}: {_fmt(w['cpi'])} ; {_fmt(w['spi'])}" for w in r["weekly"][-3:]]
    lines[-1] += "  ← corte"
    bx, by = pts[-1][0] - 7.3, pts[-1][1] + 2.2
    ax.add_patch(FancyBboxPatch((bx, by), 6.4, 0.95 * len(lines) + 0.3, boxstyle="square,pad=0.1",
                                facecolor="#FFFF00", edgecolor="#E0C000", zorder=6))
    for k, line in enumerate(reversed(lines)):
        ax.text(bx + 0.25, by + 0.55 + 0.95 * k, line, fontsize=9.5, va="center", zorder=7)
    ax.annotate("", xy=pts[-1], xytext=(bx + 6.4, by + 0.4),
                arrowprops={"arrowstyle": "->", "color": "black", "lw": 1.2}, zorder=6)
    ax.text(bx, by - 0.55, "CPI ; SPI", fontsize=8, color="#333333", zorder=7)

    # tablas de la derecha: clasificación al corte y rangos de estado
    name, color = classify(r["cpi"], r["spi"])
    tx = fig.add_axes([0.66, 0.10, 0.32, 0.74])
    tx.axis("off")
    tx.set_xlim(0, 1)
    tx.set_ylim(0, 1)

    def row(y, cells, widths, fills, bold=None, colors=None, h=0.055):
        x = 0.0
        for k, (txt, w) in enumerate(zip(cells, widths, strict=True)):
            tx.add_patch(Rectangle((x, y), w, h, facecolor=fills[k], edgecolor="black", linewidth=0.8))
            tx.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=9.5,
                    fontweight="bold" if bold and bold[k] else "normal", color=(colors or ["black"] * 3)[k])
            x += w

    title = f"Corte semana {r['status_week']}"
    row(0.86, [title], [0.75], ["white"], bold=[True])
    row(0.805, ["CPI (Costo)", _fmt(r["cpi"])], [0.45, 0.30], ["white", "white"], bold=[True, False])
    row(0.75, ["SPI (Cronograma)", _fmt(r["spi"])], [0.45, 0.30], ["white", "white"], bold=[True, False])
    row(0.695, ["Clasificación", name], [0.45, 0.30], ["white", color], bold=[True, False])
    row(0.52, ["Valores Índices", "Estado del Proyecto"], [0.5, 0.5], ["#2E5395", "#2E5395"],
        bold=[True, True], colors=["white", "white"])
    labels = ["CPI y SPI >= 1,15", "CPI y SPI >= 1,10", "CPI y SPI >= 1,00", "CPI y SPI >= 0,90", "CPI y SPI < 0,90"]
    for k, (lab, (_, st, col)) in enumerate(zip(labels, CLASSES, strict=True)):
        row(0.465 - 0.055 * k, [lab, st], [0.5, 0.5], ["white", col])
    tx.text(0.0, 0.13, f"Cuadrante IV: adelantado (SPI ≥ 1) y sobre presupuesto (CPI < 1).\n"
            f"Trayectoria S1–S{r['status_week']} en gris; punto negro = corte.", fontsize=8.8, color="#333333",
            va="top")
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    r = compute()
    (OUT / "evm.json").write_text(json.dumps(r, indent=2, ensure_ascii=False))
    chart_s_curve(r, OUT / "evm_curva_s.png")
    chart_quadrant(r, OUT / "evm_cuadrante.png")
    keys = ("bac_h", "pv_h", "ev_h", "ac_h", "spi", "cpi", "eac_h", "vac_h", "tcpi", "bac_gbp", "eac_gbp",
            "reserve_consumed_pct", "reserve_covers_overrun")
    print(json.dumps({k: r[k] for k in keys}, ensure_ascii=False))
    for w in r["weekly"]:
        print(w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
