"""Evaluación económica ERV de Vox-Causal AI: CAPEX, OPEX, VAN, TIR, Payback y B/C.

Modelo mensual a 36 meses desde el inicio del proyecto, en libras esterlinas (GBP), antes de impuestos.
  * Meses 1–3: desarrollo (CAPEX distribuido según la línea base del EVM).
  * Mes 4 en adelante: operación; el módulo se cobra como recargo (premium) del 20 % sobre la suscripción.

El OPEX de cómputo se deriva de la capacidad MEDIDA en la prueba de concepto (180 sesiones por
réplica de 1 vCPU, ver bench/results/admission_1vcpu.json). Cada supuesto lleva su fuente en SOURCES.

Salida: erv/out/finance.json, erv/out/fin_flujo_acumulado.png, erv/out/fin_tornado.png
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "out"
EVM = json.loads((OUT / "evm.json").read_text())
ADMISSION = json.loads((ROOT / "bench/results/admission_1vcpu.json").read_text())

C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"

USD_PER_GBP = 1.33
HORIZON = 36
DEV_MONTHS = 3

SOURCES = {
    "fx": "GBP/USD 1,33 (CoinCodex, oct-2026)",
    "rate": "Tarifa mediana de contratos de Machine Learning en UK £575/día (IT Jobs Watch, 6 meses a oct-2026); jornada 7,5 h",
    "wacc": "WACC sector tecnología 11,2 % (PwC Cost of Capital, feb-2026)",
    "aca": "Container Apps consumo: US$0,000024/vCPU-s y US$0,000003/GiB-s activos (DevZero, lista de precios Azure, sep-2026)",
    "apim": "API Management Standard v2 US$700/mes; admite WebSocket (digitalapi.ai, oct-2026; Microsoft Learn)",
    "sb": "Service Bus Premium 1 MU ≈ US$677/mes, requerido para Private Endpoints (CloudToolStack; verificar en calculadora)",
    "aoai": "Azure OpenAI GPT-4o mini US$0,15 / US$0,60 por millón de tokens de entrada / salida (oct-2026)",
    "blob": "Blob Storage Hot LRS US$0,018/GB-mes; escrituras US$0,065 por 10.000 (nOps, may-2026)",
    "la": "Log Analytics US$2,30/GB, 5 GB/mes gratis (ManageEngine, oct-2026)",
    "seat_price": "Funciones de IA para contact center US$75–155 por agente/mes (Bright Pattern, feb-2026); base £60 ≈ US$80",
    "agent_cost": "Sueldo base agente de call center UK £18.896/año (PayScale) + 30 % de cargas laborales (supuesto)",
    "churn": "Churn B2B enterprise ≈ 11–22 % anual (koji.so, 2026)",
    "aht": "Copilot for Service redujo el AHT en 12 % (Microsoft vía CX Today, 2023)",
}

BASE = {
    "name": "Base",
    "installed_seats": 5000,        # SUPUESTO: puestos de agente suscritos en UK y Europa
    "adoption": 0.40,               # SUPUESTO: % de puestos que contrata el módulo premium
    "ramp_months": 12,              # SUPUESTO: meses hasta alcanzar la adopción objetivo
    "base_price_gbp": 60.0,         # SUPUESTO con referencia de mercado (SOURCES.seat_price)
    "premium_pct": 0.20,            # dato del caso
    "retention_pp": 0.0,            # reducción de churn anual (solo escenario optimista)
    "calls_per_seat_month": 1000,   # SUPUESTO: ~7 llamadas/h × 160 h × ocupación
    "minutes_per_call": 5.0,        # SUPUESTO
    "peak_concurrency": 0.60,       # SUPUESTO: llamadas simultáneas en hora punta / puestos
    "opex_factor": 1.0,
    "capex_factor": 1.0,
    "wacc": 0.112,
    "maintenance_h_month": 24,      # SUPUESTO: operación MLOps (reentrenos, guardia, parches)
}


def scenarios() -> list[dict]:
    pes = {**BASE, "name": "Pesimista", "adoption": 0.20, "ramp_months": 18, "base_price_gbp": 45.0,
           "opex_factor": 1.30, "capex_factor": 1.25}
    opt = {**BASE, "name": "Optimista", "adoption": 0.60, "ramp_months": 9, "base_price_gbp": 75.0,
           "retention_pp": 0.02}
    return [pes, BASE, opt]


def sessions_per_replica() -> int:
    """Capacidad medida: sesiones aceptadas por réplica de 1 vCPU con p95 < 200 ms."""
    r = next(x for x in ADMISSION if x["streams"] == 400)
    assert r["pct_under_200ms"] == 100.0
    return r["streams"] - r["errors"].get("closed_1013", 0)


CAP = sessions_per_replica()          # 180
RATE = EVM["rate_gbp_h"]


def usd(x: float) -> float:
    return x / USD_PER_GBP


def opex_month(seats: float, p: dict) -> dict:
    """OPEX mensual en GBP para un número de puestos activos."""
    secs = 730 * 3600
    calls = seats * p["calls_per_seat_month"]
    replicas = max(2, math.ceil(seats * p["peak_concurrency"] / CAP) + 1)     # N+1, mínimo 2 (alta disponibilidad)
    api = replicas * secs * (0.000024 + 2 * 0.000003)                          # 1 vCPU + 2 GiB, activo 24/7
    batch = 12 * 730 * 60 * (0.000024 + 2 * 0.000003) + 4.3 * 600 * (2 * 0.000024 + 4 * 0.000003)
    aoai = calls * (500 * 0.15 + 150 * 0.60) / 1e6
    gb = calls * p["minutes_per_call"] * 0.48 / 1000                           # G.711 64 kbps, 30 días
    blob = gb * 0.018 + calls * 0.065 / 10_000
    la = max(0.0, 10 + calls * 1e-6 - 5) * 2.30
    fixed = 700 + 677.44 + 20 + 3 * 7.30 + 10                                  # APIM, SB Premium, ACR, PE, KV
    cloud_usd = api + batch + aoai + blob + la + fixed
    items = {
        "api_compute": usd(api), "batch_compute": usd(batch), "azure_openai": usd(aoai), "audio_storage": usd(blob),
        "log_analytics": usd(la), "apim": usd(700), "service_bus": usd(677.44), "otros_azure": usd(20 + 21.9 + 10),
    }
    items = {k: v * p["opex_factor"] for k, v in items.items()}
    items["mantenimiento_mlops"] = p["maintenance_h_month"] * RATE * p["opex_factor"]
    return {"replicas": replicas, "calls": calls, "cloud_gbp": usd(cloud_usd) * p["opex_factor"],
            "items": items, "total": sum(items.values())}


def flows(p: dict) -> dict:
    capex_total = EVM["bac_gbp"] * 1.10 * p["capex_factor"]          # BAC + 10 % de reserva
    pv = EVM["pv_curve_pct"]
    by_month = [pv[3] / 100, (pv[7] - pv[3]) / 100, (100 - pv[7]) / 100]   # 4 semanas por mes
    months = []
    for m in range(1, HORIZON + 1):
        capex = capex_total * by_month[m - 1] if m <= DEV_MONTHS else 0.0
        if m <= DEV_MONTHS:
            seats, revenue, retention, opex = 0.0, 0.0, 0.0, 0.0
            op = None
        else:
            k = m - DEV_MONTHS
            seats = p["installed_seats"] * p["adoption"] * min(1.0, k / p["ramp_months"])
            revenue = seats * p["base_price_gbp"] * p["premium_pct"]
            retention = seats * p["base_price_gbp"] * p["retention_pp"] * min(1.0, k / 12)
            op = opex_month(seats, p)
            opex = op["total"]
        months.append({"m": m, "seats": seats, "revenue": revenue, "retention": retention,
                       "capex": capex, "opex": opex, "net": revenue + retention - capex - opex,
                       "replicas": op["replicas"] if op else 0})
    return {"capex_total": capex_total, "months": months}


def npv(rate_m: float, cfs: list[float]) -> float:
    return sum(cf / (1 + rate_m) ** i for i, cf in enumerate(cfs, start=1))


def irr(cfs: list[float]) -> float | None:
    lo, hi = -0.99, 1.0
    if npv(lo, cfs) * npv(hi, cfs) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo, cfs) * npv(mid, cfs) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def evaluate(p: dict) -> dict:
    f = flows(p)
    ms = f["months"]
    r_m = (1 + p["wacc"]) ** (1 / 12) - 1
    net = [x["net"] for x in ms]
    benefits = [x["revenue"] + x["retention"] for x in ms]
    costs = [x["capex"] + x["opex"] for x in ms]
    cum, dcum, pb, dpb = 0.0, 0.0, None, None
    cum_series, dcum_series = [], []
    for i, cf in enumerate(net, start=1):
        cum += cf
        dcum += cf / (1 + r_m) ** i
        cum_series.append(cum)
        dcum_series.append(dcum)
        if pb is None and cum >= 0 and i > DEV_MONTHS:
            pb = i
        if dpb is None and dcum >= 0 and i > DEV_MONTHS:
            dpb = i
    irr_m = irr(net)
    steady = opex_month(p["installed_seats"] * p["adoption"], p)
    year = [{"year": y,
             "revenue": sum(x["revenue"] for x in ms[(y - 1) * 12:y * 12]),
             "retention": sum(x["retention"] for x in ms[(y - 1) * 12:y * 12]),
             "capex": sum(x["capex"] for x in ms[(y - 1) * 12:y * 12]),
             "opex": sum(x["opex"] for x in ms[(y - 1) * 12:y * 12]),
             "net": sum(x["net"] for x in ms[(y - 1) * 12:y * 12])} for y in (1, 2, 3)]
    return {
        "scenario": p["name"], "params": {k: v for k, v in p.items() if k != "name"},
        "capex_gbp": f["capex_total"],
        "npv_gbp": npv(r_m, net),
        "irr_annual": (1 + irr_m) ** 12 - 1 if irr_m is not None else None,
        "payback_month": pb, "discounted_payback_month": dpb,
        "payback_from_launch_months": pb - DEV_MONTHS if pb else None,
        "bc_ratio": npv(r_m, benefits) / npv(r_m, costs),
        "pv_benefits": npv(r_m, benefits), "pv_costs": npv(r_m, costs),
        "steady_state": {"seats": p["installed_seats"] * p["adoption"], "replicas": steady["replicas"],
                         "opex_month": steady["total"], "cloud_month": steady["cloud_gbp"],
                         "revenue_month": p["installed_seats"] * p["adoption"] * p["base_price_gbp"] * p["premium_pct"],
                         "items": steady["items"]},
        "years": year,
        "cum": cum_series, "dcum": dcum_series,
    }


def breakeven_adoption(p: dict) -> float:
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if evaluate({**p, "adoption": mid})["npv_gbp"] < 0:
            lo = mid
        else:
            hi = mid
    return hi


def tornado(p: dict) -> list[dict]:
    tests = [
        ("Adopción del módulo (20 % ↔ 60 %)", "adoption", 0.20, 0.60),
        ("Precio base por puesto (£45 ↔ £75)", "base_price_gbp", 45.0, 75.0),
        ("Meses de rampa (18 ↔ 6)", "ramp_months", 18, 6),
        ("OPEX (+30 % ↔ −20 %)", "opex_factor", 1.30, 0.80),
        ("CAPEX (+50 % ↔ −10 %)", "capex_factor", 1.50, 0.90),
        ("WACC (15 % ↔ 8 %)", "wacc", 0.15, 0.08),
    ]
    base = evaluate(p)["npv_gbp"]
    out = []
    for label, key, low, high in tests:
        a = evaluate({**p, key: low})["npv_gbp"]
        b = evaluate({**p, key: high})["npv_gbp"]
        out.append({"label": label, "low": a, "high": b, "base": base, "swing": abs(b - a)})
    return sorted(out, key=lambda x: x["swing"])


def customer_value(p: dict) -> dict:
    loaded_month = 18896 * 1.30 / 12
    premium = p["base_price_gbp"] * p["premium_pct"]
    return {"agent_cost_month": loaded_month, "saving_15": loaded_month * 0.15, "saving_12": loaded_month * 0.12,
            "premium_month": premium, "value_to_price_15": loaded_month * 0.15 / premium,
            "value_to_price_12": loaded_month * 0.12 / premium}


def _style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=10)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def gbp_k(x: float) -> str:
    sign = "−" if x < 0 else ""
    return f"{sign}£{abs(x)/1000:,.0f}k".replace(",", ".")


def chart_cum(results: list[dict], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5), dpi=200)
    _style(ax)
    months = list(range(1, HORIZON + 1))
    offsets = {"Optimista": (-78, 10), "Base": (8, -16), "Pesimista": (8, -16)}
    for r, c in zip(results, (C2, C1, C3), strict=True):
        ax.plot(months, [v / 1000 for v in r["dcum"]], color=c, lw=2, label=f"{r['scenario']}")
        if r["discounted_payback_month"]:
            m = r["discounted_payback_month"]
            ax.scatter([m], [r["dcum"][m - 1] / 1000], s=40, color=c, edgecolor=SURF, linewidth=1.5, zorder=3)
            ax.annotate(f"payback mes {m}", (m, r["dcum"][m - 1] / 1000), xytext=offsets[r["scenario"]],
                        textcoords="offset points", fontsize=8.5, color=INK2)
        ax.annotate(f"VAN {gbp_k(r['npv_gbp'])}", (HORIZON, r["dcum"][-1] / 1000), xytext=(6, 0),
                    textcoords="offset points", fontsize=9, color=INK, va="center", fontweight="bold")
    ax.axhline(0, color=INK2, lw=1)
    ax.axvspan(0.5, DEV_MONTHS + 0.5, color="#f2a900", alpha=0.12)
    ax.text(0.7, ax.get_ylim()[1] * 0.92, "Desarrollo\n(CAPEX)", color=INK2, fontsize=8.5, va="top")
    ax.set_xlim(0.5, HORIZON + 5)
    ax.set_xlabel("Mes desde el inicio del proyecto", color=INK2)
    ax.set_ylabel("Flujo neto descontado acumulado (miles de £)", color=INK2)
    ax.set_title("Flujo de caja descontado acumulado por escenario (WACC 11,2 %)", color=INK, fontsize=12.5,
                 loc="left", fontweight="bold")
    ax.legend(loc="upper left", frameon=False, fontsize=9.5, labelcolor=INK, bbox_to_anchor=(0.12, 1))
    fig.tight_layout()
    fig.savefig(path, facecolor=SURF)
    plt.close(fig)


def chart_tornado(rows: list[dict], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=200)
    _style(ax)
    ax.grid(axis="y", visible=False)
    base = rows[0]["base"] / 1000
    for i, r in enumerate(rows):
        lo, hi = r["low"] / 1000, r["high"] / 1000
        ax.barh(i, lo - base, left=base, color=C2, height=0.55, edgecolor=SURF, linewidth=2)
        ax.barh(i, hi - base, left=base, color=C1, height=0.55, edgecolor=SURF, linewidth=2)
        ax.text(min(lo, hi) - 8, i, gbp_k(min(r["low"], r["high"])), ha="right", va="center", fontsize=8.5, color=INK2)
        ax.text(max(lo, hi) + 8, i, gbp_k(max(r["low"], r["high"])), ha="left", va="center", fontsize=8.5, color=INK2)
    ax.axvline(base, color=INK, lw=1.2)
    ax.axvline(0, color=INK2, lw=1, ls=":")
    ax.text(0, -0.75, " VAN = 0", color=INK2, fontsize=8.5)
    ax.set_ylim(-0.9, len(rows) - 0.5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r["label"] for r in rows], color=INK, fontsize=9.5)
    ax.set_xlabel("VAN a 36 meses (miles de £) — barra naranja: valor desfavorable · azul: favorable", color=INK2)
    ax.set_title(f"Sensibilidad del VAN (escenario base {gbp_k(rows[0]['base'])})", color=INK, fontsize=12.5,
                 loc="left", fontweight="bold")
    xmin = min(min(r["low"], r["high"]) for r in rows) / 1000
    xmax = max(max(r["low"], r["high"]) for r in rows) / 1000
    ax.set_xlim(min(0, xmin) - 90, xmax + 90)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURF)
    plt.close(fig)


def main() -> int:
    results = [evaluate(p) for p in scenarios()]
    tor = tornado(BASE)
    be = breakeven_adoption(BASE)
    out = {
        "currency": "GBP", "usd_per_gbp": USD_PER_GBP, "horizon_months": HORIZON, "dev_months": DEV_MONTHS,
        "sessions_per_replica_measured": CAP, "rate_gbp_h": RATE, "sources": SOURCES,
        "scenarios": [{k: v for k, v in r.items() if k not in ("cum", "dcum")} for r in results],
        "tornado": tor,
        "breakeven_adoption": be, "breakeven_seats": be * BASE["installed_seats"],
        "customer_value": customer_value(BASE),
        "kpi_capacity_opex": opex_month(1500 / BASE["peak_concurrency"], BASE),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "finance.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=float))
    chart_cum(results, OUT / "fin_flujo_acumulado.png")
    chart_tornado(tor, OUT / "fin_tornado.png")
    for r in results:
        print(f"{r['scenario']:10s} CAPEX £{r['capex_gbp']:,.0f}  VAN £{r['npv_gbp']:,.0f}  "
              f"TIR {r['irr_annual'] if r['irr_annual'] is None else round(r['irr_annual']*100,1)}%  "
              f"payback mes {r['payback_month']} (desc {r['discounted_payback_month']})  B/C {r['bc_ratio']:.2f}  "
              f"OPEX estable £{r['steady_state']['opex_month']:,.0f}/mes réplicas {r['steady_state']['replicas']} "
              f"ingreso £{r['steady_state']['revenue_month']:,.0f}/mes")
    print("break-even adopción", round(be * 100, 2), "% =", round(be * BASE["installed_seats"]), "puestos")
    print("valor cliente", {k: round(v, 1) for k, v in out["customer_value"].items()})
    k = out["kpi_capacity_opex"]
    print("OPEX a 1.500 concurrentes:", k["replicas"], "réplicas", round(k["total"]), {a: round(b) for a, b in k["items"].items()})
    for t in tor:
        print(f"  {t['label']:45s} {t['low']:>10,.0f} {t['high']:>10,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
