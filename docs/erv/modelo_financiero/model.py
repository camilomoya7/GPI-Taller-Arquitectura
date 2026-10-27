"""Modelo financiero ERV — integración de Vox-Causal AI en Alloxentric SpA.

Moneda: GBP. Horizonte: 36 meses, flujos al final de cada mes, sin valor terminal,
antes de impuestos y a precios constantes. Los datos del caso (800 HH, -15 % TTR,
+20 % de recargo) se toman literalmente; todo lo demás es supuesto de modelación
con fuente o justificación en SOURCES.
"""
import json
import math
from copy import deepcopy
from pathlib import Path

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

FX_GBP_PER_USD = 0.75472  # implícito en la lista GBP de Azure (Service Bus Premium 0,70/0,9275; APIM Std v2 0,7237/0,9589)
USD = {  # Azure Retail Prices API, uksouth, consultado 27-10-2026
    "aca_vcpu_s": 0.000034, "aca_mem_gib_s": 0.000004, "acr_basic_day": 0.1666, "sb_std_base_month": 10.0,
    "sb_std_ops_m_13_100": 0.8, "sb_premium_mu_h": 0.9275, "apim_std_v2_unit_h": 0.9589,
    "aoai_4o_mini_in_1k": 0.00015, "aoai_4o_mini_out_1k": 0.0006, "blob_hot_lrs_gb_month": 0.0192,
    "blob_hot_write_10k": 0.059, "log_analytics_gb": 2.88,
}
GBP = {k: v * FX_GBP_PER_USD for k, v in USD.items()}
H_MONTH = 730
HOURS_PER_DAY_RATE = 7.5

BASE = {
    # --- Dados por el caso
    "capex_hh": 800, "ttr_reduction": 0.15, "premium_rate": 0.20,
    "peak_concurrency": 1500,
    # --- Supuestos de modelación
    "day_rate_gbp": 550.0,            # mediana UK MLOps contract (itjobswatch, 6 meses a 27-10-2026)
    "capex_reserve": 0.10,            # reserva de contingencia sobre el BAC (línea base EVM del caso)
    "capex_m1": 0.3533, "capex_m2": 0.4342, "capex_m3": 0.2125,  # meses 1-3 según la PV del EVM (semanas 4, 8 y 12)
    "golive_month": 4,                # salida a producción tras las 12 semanas de integración
    "ramp_start": 4, "ramp_end": 15,  # adopción lineal desde 10 % hasta 100 % del objetivo
    "licensed_seats": 2000,           # 1.500 llamadas concurrentes con ocupación ≈ 75 %
    "adoption": 0.60,                 # fracción de puestos que contrata el módulo
    "seat_price_gbp": 60.0,           # precio base mensual por puesto (no informado por Alloxentric)
    # Carga (al 100 % de los 1.500 concurrentes)
    "business_share": 0.50, "offhours_share": 0.10,   # concurrencia media / pico, 12 h + 12 h
    "aht_min": 9.22,                  # CCMA Benchmark 2025: 9 min 13 s por interacción
    "calls_per_replica": 180,         # PoC del equipo: tope por réplica de 1 vCPU (documentado, EVIDENCIA.md)
    "redundancy": 1,                  # N+1
    "min_replicas": 2,                # alta disponibilidad: nunca menos de 2 réplicas
    "vcpu_per_replica": 1.0, "gib_per_replica": 2.0,
    "audio_mb_per_min": 0.48,         # G.711 (64 kbit/s), telefonía estándar
    "audio_retention_days": 30,       # política de la PoC (UK GDPR)
    "msgs_per_call": 3,
    "tokens_in": 600, "tokens_out": 150,
    "kb_per_call": 50, "retention_months": 12, "writes_per_call": 2,
    "log_gb_month": 60,
    "sb_premium_mu": 1,               # Premium: requerido para Private Endpoints (aislamiento de zonas)
    "apim_units": 1,                  # APIM Standard v2 dedicado como gateway WebSocket
    "mlops_hours_month": 20,          # recalibración, monitoreo y soporte del modelo (supuesto)
    "cloud_opex_factor": 1.0,
    "discount_annual": 0.12,          # Damodaran ene-2026, Europa, Software (System & Application): 8,70 % + 3,3 pp riesgo de proyecto
    "horizon": 36,
    # Valor para el cliente (no entra en el VAN de Alloxentric)
    "agent_salary_gbp": 28667.0,      # CCMA 2025, salario medio frontline Londres
    "agent_hours_year": 1950.0, "oncost_factor": 1.25,
}

SCENARIOS = {
    "Optimista": {"day_rate_gbp": 425.0, "seat_price_gbp": 80.0, "adoption": 0.75, "ramp_end": 12,
                  "cloud_opex_factor": 0.85, "mlops_hours_month": 15},
    "Base": {},
    "Pesimista": {"day_rate_gbp": 775.0, "capex_hh": 1000, "seat_price_gbp": 40.0, "adoption": 0.25,
                  "golive_month": 7, "ramp_start": 7, "ramp_end": 24,
                  "calls_per_replica": 100, "mlops_hours_month": 40, "cloud_opex_factor": 1.15},
}


def params(name):
    p = deepcopy(BASE)
    p.update(SCENARIOS[name])
    return p


def adoption_curve(p, m):
    if m < p["ramp_start"]:
        return 0.0
    if m >= p["ramp_end"]:
        return 1.0
    return 0.10 + 0.90 * (m - p["ramp_start"]) / (p["ramp_end"] - p["ramp_start"])


def replicas_for(p, concurrent):
    return max(p["min_replicas"], math.ceil(concurrent / p["calls_per_replica"]) + p["redundancy"]) if concurrent > 0 else p["min_replicas"]


def full_load(p):
    """Consumo mensual si el 100 % de los puestos objetivo usa el módulo."""
    calls_per_h = 60.0 / p["aht_min"]
    hours = H_MONTH / 2
    conc = (p["business_share"], p["offhours_share"])
    calls = sum(p["peak_concurrency"] * s * calls_per_h * hours for s in conc)
    return {"calls": calls, "peak_replicas": replicas_for(p, p["peak_concurrency"])}


def replica_hours(p, share):
    hours = H_MONTH / 2
    return sum(replicas_for(p, p["peak_concurrency"] * s * share) * hours for s in (p["business_share"], p["offhours_share"]))


def opex_month(p, share):
    """OPEX mensual (GBP) dado el uso efectivo `share` = puestos activos / puestos licenciados."""
    fl = full_load(p)
    f = p["cloud_opex_factor"]
    calls = fl["calls"] * share
    rh = replica_hours(p, share)
    replica_h_price = 3600 * (p["vcpu_per_replica"] * GBP["aca_vcpu_s"] + p["gib_per_replica"] * GBP["aca_mem_gib_s"])
    audio_gb = calls * p["aht_min"] * p["audio_mb_per_min"] / 1000 * p["audio_retention_days"] / 30.4
    stored_gb = calls * p["kb_per_call"] / 1e6 * p["retention_months"]
    ops_m = calls * p["msgs_per_call"] / 1e6
    rows = {
        "API de inferencia (Container Apps, réplicas 1 vCPU)": f * rh * replica_h_price,
        "Jobs batch (entrenamiento y worker)": f * 60 * replica_h_price,
        "Azure Service Bus Standard (solo sin Premium)": f * (p["sb_premium_mu"] == 0) * (GBP["sb_std_base_month"] + max(0, ops_m - 13) * GBP["sb_std_ops_m_13_100"]),
        "Azure Service Bus Premium (Private Endpoints)": f * p["sb_premium_mu"] * H_MONTH * GBP["sb_premium_mu_h"],
        "Azure API Management Standard v2 (gateway WebSocket)": f * p["apim_units"] * H_MONTH * GBP["apim_std_v2_unit_h"],
        "Azure OpenAI gpt-4o-mini (explicación post-llamada)": f * calls * (p["tokens_in"] / 1000 * GBP["aoai_4o_mini_in_1k"]
                                                                            + p["tokens_out"] / 1000 * GBP["aoai_4o_mini_out_1k"]),
        "Blob: grabaciones (30 días) y resultados": f * ((audio_gb + stored_gb) * GBP["blob_hot_lrs_gb_month"]
                                                        + calls * p["writes_per_call"] / 1e4 * GBP["blob_hot_write_10k"]),
        "Container Registry Basic": f * 30.4 * GBP["acr_basic_day"],
        "Log Analytics (telemetría y auditoría)": f * max(0, p["log_gb_month"] - 5) * GBP["log_analytics_gb"],
        "Operación MLOps (horas de ingeniería)": p["mlops_hours_month"] * p["day_rate_gbp"] / HOURS_PER_DAY_RATE,
    }
    return rows


def flows(p):
    rate = p["day_rate_gbp"] / HOURS_PER_DAY_RATE
    capex_total = p["capex_hh"] * rate * (1 + p["capex_reserve"])
    months = []
    for m in range(1, p["horizon"] + 1):
        capex = capex_total * p.get(f"capex_m{m}", 0.0)
        a = adoption_curve(p, m)
        seats = p["licensed_seats"] * p["adoption"] * a
        share = seats / p["licensed_seats"]
        live = m >= p["golive_month"]
        if live and share == 0:
            share = 0.05 * p["adoption"]  # piloto: tráfico reducido sin cobro
        opex_rows = opex_month(p, share) if live else {}
        opex = sum(opex_rows.values())
        revenue = seats * p["seat_price_gbp"] * p["premium_rate"]
        months.append({"mes": m, "capex": capex, "opex": opex, "ingresos": revenue, "puestos": seats,
                       "flujo": revenue - opex - capex})
    return capex_total, months


def npv(rate_m, cfs):
    return sum(cf / (1 + rate_m) ** (i + 1) for i, cf in enumerate(cfs))


def irr_monthly(cfs):
    lo, hi = -0.99, 10.0
    f = lambda r: npv(r, cfs)  # noqa: E731
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def payback(cfs, rate_m=None):
    acc = 0.0
    for i, cf in enumerate(cfs):
        v = cf / (1 + rate_m) ** (i + 1) if rate_m is not None else cf
        prev = acc
        acc += v
        if acc >= 0 and prev < 0:
            return round(i + (-prev / v if v else 0), 1)
    return None


def evaluate(p):
    capex_total, ms = flows(p)
    rm = (1 + p["discount_annual"]) ** (1 / 12) - 1
    cfs = [x["flujo"] for x in ms]
    pv_rev = npv(rm, [x["ingresos"] for x in ms])
    pv_cost = npv(rm, [x["opex"] + x["capex"] for x in ms])
    irr_m = irr_monthly(cfs)
    steady = ms[-1]
    fl = full_load(p)
    share_ss = p["adoption"]
    agent_rate = p["agent_salary_gbp"] / p["agent_hours_year"] * p["oncost_factor"]
    saving_call = p["aht_min"] * p["ttr_reduction"] / 60 * agent_rate
    calls_seat = fl["calls"] / p["licensed_seats"]
    return {
        "capex": capex_total, "tarifa_hora": p["day_rate_gbp"] / HOURS_PER_DAY_RATE,
        "van": npv(rm, cfs), "tir_mensual": irr_m,
        "tir_anual": (1 + irr_m) ** 12 - 1 if irr_m is not None else None,
        "payback_meses": payback(cfs), "payback_descontado_meses": payback(cfs, rm),
        "bc": pv_rev / pv_cost, "vp_ingresos": pv_rev, "vp_costos": pv_cost,
        "opex_estable_mes": steady["opex"], "ingreso_estable_mes": steady["ingresos"],
        "opex_detalle_estable": opex_month(p, share_ss),
        "flujo_acumulado": [round(sum(cfs[: i + 1]), 2) for i in range(len(cfs))],
        "meses": ms, "llamadas_mes_100": fl["calls"], "replicas_pico": fl["peak_replicas"],
        "replica_h_mes_100": replica_hours(p, 1.0), "replica_h_mes_adopcion": replica_hours(p, p["adoption"]),
        "cliente_ahorro_por_llamada": saving_call, "cliente_ahorro_puesto_mes": saving_call * calls_seat,
        "recargo_puesto_mes": p["seat_price_gbp"] * p["premium_rate"], "llamadas_por_puesto_mes": calls_seat,
    }


def breakeven_price(name):
    p = params(name)
    lo, hi = 0.0, 200.0
    for _ in range(80):
        mid = (lo + hi) / 2
        p["seat_price_gbp"] = mid
        if evaluate(p)["van"] < 0:
            lo = mid
        else:
            hi = mid
    return hi


def breakeven_adoption(name):
    p = params(name)
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        p["adoption"] = mid
        if evaluate(p)["van"] < 0:
            lo = mid
        else:
            hi = mid
    return hi if evaluate({**p, "adoption": 1.0})["van"] >= 0 else None


def tornado():
    base = evaluate(params("Base"))["van"]
    out = []
    for key, label in [("seat_price_gbp", "Precio base por puesto"), ("adoption", "Adopción del módulo"),
                       ("day_rate_gbp", "Tarifa de ingeniería (CAPEX y MLOps)"), ("cloud_opex_factor", "Costo cloud"),
                       ("mlops_hours_month", "Horas MLOps mensuales"), ("discount_annual", "Tasa de descuento"),
                       ("calls_per_replica", "Capacidad por réplica"),
                       ("capex_hh", "Horas de integración")]:
        vals = []
        for f in (0.8, 1.2):
            p = params("Base")
            p[key] = p[key] * f
            vals.append(evaluate(p)["van"])
        out.append({"variable": label, "van_-20": vals[0], "van_+20": vals[1], "rango": abs(vals[1] - vals[0])})
    out.sort(key=lambda x: -x["rango"])
    return base, out


def discount_sensitivity():
    res = {}
    for r in (0.087, 0.12, 0.16):
        p = params("Base")
        p["discount_annual"] = r
        res[f"{r:.3f}"] = evaluate(p)["van"]
    return res


if __name__ == "__main__":
    results = {n: evaluate(params(n)) for n in SCENARIOS}
    base_van, torn = tornado()
    summary = {
        "fx_gbp_por_usd": FX_GBP_PER_USD, "precios_gbp": GBP,
        "escenarios": {n: {k: v for k, v in r.items() if k not in ("meses",)} for n, r in results.items()},
        "punto_equilibrio_precio_puesto_base": breakeven_price("Base"),
        "punto_equilibrio_adopcion_base": breakeven_adoption("Base"),
        "punto_equilibrio_precio_puesto_pesimista": breakeven_price("Pesimista"),
        "tornado_base": torn, "sensibilidad_descuento": discount_sensitivity(),
        "supuestos_base": {k: v for k, v in BASE.items()},
        "escenarios_definicion": SCENARIOS,
    }
    (OUT / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "flows.json").write_text(json.dumps({n: r["meses"] for n, r in results.items()}, ensure_ascii=False), encoding="utf-8")
    for n, r in results.items():
        print(f"{n:10} CAPEX £{r['capex']:,.0f} | OPEX estable £{r['opex_estable_mes']:,.0f}/mes | ingreso estable £{r['ingreso_estable_mes']:,.0f}/mes | "
              f"VAN £{r['van']:,.0f} | TIR anual {r['tir_anual'] if r['tir_anual'] is None else round(r['tir_anual']*100,1)}% | "
              f"payback {r['payback_meses']} m (desc. {r['payback_descontado_meses']}) | B/C {r['bc']:.2f}")
    b = results["Base"]
    for n, r in results.items():
        print(n, "réplicas pico:", r["replicas_pico"], "réplica-h/mes 100%:", round(r["replica_h_mes_100"]), "con adopción:", round(r["replica_h_mes_adopcion"]))
    print("Base: llamadas/mes al 100%:", round(b["llamadas_mes_100"]))
    print("Cliente: ahorro/llamada £%.3f, ahorro/puesto/mes £%.0f vs recargo £%.0f (llamadas/puesto %.0f)" % (
        b["cliente_ahorro_por_llamada"], b["cliente_ahorro_puesto_mes"], b["recargo_puesto_mes"], b["llamadas_por_puesto_mes"]))
    print("Equilibrio precio base/puesto (Base):", round(summary["punto_equilibrio_precio_puesto_base"], 2),
          "| adopción equilibrio:", summary["punto_equilibrio_adopcion_base"],
          "| precio equilibrio pesimista:", round(summary["punto_equilibrio_precio_puesto_pesimista"], 2))
    print("Descuento:", {k: round(v) for k, v in summary["sensibilidad_descuento"].items()})
    for t in torn:
        print(f"  {t['variable']:40} -20%: £{t['van_-20']:,.0f}  +20%: £{t['van_+20']:,.0f}")
    print("OPEX detalle estable Base:", {k: round(v, 1) for k, v in b["opex_detalle_estable"].items()})
