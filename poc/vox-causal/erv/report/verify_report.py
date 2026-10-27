"""Verifica que el informe Word contenga exactamente las cifras de los archivos de resultados.

Recalcula en Python (independiente del generador JS) el formato es-CL de cada cifra clave y comprueba que
aparezca en el texto del .docx. También detecta marcadores rotos (undefined, NaN, null, ${...}).
Uso:  python erv/report/verify_report.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCX = ROOT / "erv/report/Informe_ERV_VoxCausal_Grupo1.docx"


def J(p: str):
    return json.loads((ROOT / p).read_text())


def num(x: float, d: int = 0) -> str:
    s = f"{abs(x):,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if x < 0 else "") + s


def gbp(x: float) -> str:
    return ("−£" if x < 0 else "£") + num(abs(x))


def main() -> int:
    text = subprocess.run(["pandoc", "-t", "plain", "--wrap=none", str(DOCX)], capture_output=True, text=True,
                          check=True).stdout
    evm, fin, met, q = J("erv/out/evm.json"), J("erv/out/finance.json"), J("services/inference_api/model/metrics.json"), J("erv/out/quality.json")
    stg, adm = J("bench/results/server_stages.json"), J("bench/results/admission_1vcpu.json")
    sc = {s["scenario"]: s for s in fin["scenarios"]}
    a180 = next(r for r in adm if r["streams"] == 180)
    a400 = next(r for r in adm if r["streams"] == 400)
    expect = {
        "BAC £": gbp(evm["bac_gbp"]),
        "EV h": num(evm["ev_h"]), "AC h": num(evm["ac_h"]),
        "SPI %": num(evm["spi"] * 100, 1) + " %", "CPI %": num(evm["cpi"] * 100, 1) + " %",
        "EAC h": num(evm["eac_h"], 1) + " h", "reserva consumida": num(evm["reserve_consumed_pct"], 1) + " %",
        "TCPI": num(evm["tcpi"], 3), "clasificación EVM": f"clasificación {evm['classification']}",
        "VAN base": gbp(sc["Base"]["npv_gbp"]), "VAN pesimista": gbp(sc["Pesimista"]["npv_gbp"]),
        "VAN optimista": gbp(sc["Optimista"]["npv_gbp"]),
        "B/C base": num(sc["Base"]["bc_ratio"], 2), "payback base": f"Mes {sc['Base']['payback_month']}",
        "CAPEX base": gbp(sc["Base"]["capex_gbp"]), "CAPEX pesimista": gbp(sc["Pesimista"]["capex_gbp"]),
        "OPEX base": gbp(sc["Base"]["steady_state"]["opex_month"]),
        "ingreso base": gbp(sc["Base"]["steady_state"]["revenue_month"]),
        "equilibrio puestos": num(fin["breakeven_seats"]) + " puestos",
        "equilibrio %": num(fin["breakeven_adoption"] * 100, 1) + " %",
        "valor/precio": num(fin["customer_value"]["value_to_price_15"], 1) + " veces",
        "ahorro agente": gbp(fin["customer_value"]["saving_15"]),
        "OPEX KPI": gbp(fin["kpi_capacity_opex"]["total"]),
        "error ATE espera": num(met["treatments"]["long_wait"]["error_dml"], 4),
        "error correlacional": num(met["treatments"]["long_wait"]["error_naive"], 4),
        "MAE": num(met["stress_calibration"]["mae"], 3),
        "servidor p95": num(stg["server_total"]["p95_ms"], 2) + " ms",
        "e2e p95 180": num(a180["p95_ms"], 1) + " ms",
        "sobrecarga p95": num(a400["p95_ms"], 1) + " ms",
        "derivadas": f"{a400['errors']['closed_1013']} derivadas",
        "pruebas": f"{q['tests']} pruebas", "cobertura": f"{num(q['coverage_pct'], 0)} %",
    }
    missing = {k: v for k, v in expect.items() if v not in text}
    broken = re.findall(r"undefined|NaN|\bnull\b|\$\{", text)
    for k, v in expect.items():
        print(f"{'✔' if k not in missing else '✘'} {k:22s} {v}")
    if broken:
        print("Marcadores rotos:", set(broken))
    print(f"\n{len(expect) - len(missing)}/{len(expect)} cifras verificadas en el informe")
    return 1 if missing or broken else 0


if __name__ == "__main__":
    sys.exit(main())
