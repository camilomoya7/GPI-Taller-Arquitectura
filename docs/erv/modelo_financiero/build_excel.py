"""Genera el modelo financiero en Excel con fórmulas vivas (mismo modelo que model.py)."""
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).parent))
import model as M  # noqa: E402

OUTFILE = Path(sys.argv[1])
NAVY, TEAL, GREY = "1B3A5F", "0E7C86", "F2F4F7"
hdr = Font(bold=True, color="FFFFFF")
fill_h = PatternFill("solid", fgColor=NAVY)
fill_in = PatternFill("solid", fgColor="FFF4D6")
fill_case = PatternFill("solid", fgColor="E6F4EA")
thin = Border(*(Side(style="thin", color="D7E0EA"),) * 4)
NAMES = list(M.SCENARIOS)  # Optimista, Base, Pesimista
COLS = {"Optimista": "B", "Base": "C", "Pesimista": "D"}

wb = Workbook()
ws = wb.active
ws.title = "Supuestos"
ws["A1"] = "Modelo financiero ERV — Vox-Causal AI en Alloxentric SpA (GBP, 36 meses, flujos a fin de mes)"
ws["A1"].font = Font(bold=True, size=13, color=NAVY)
ws["A2"] = "Verde = dato del caso. Amarillo = supuesto de modelación (ver columna Fuente). Cambie las celdas para recalcular."
ws.append([])
ws.append(["Parámetro", "Optimista", "Base", "Pesimista", "Unidad", "Fuente / justificación"])
for c in ws[4]:
    c.font, c.fill = hdr, fill_h

ROWS = [
    ("capex_hh", "Horas-hombre de integración", "HH", "Caso PIA (800 HH); pesimista +25 % de desvío", True),
    ("day_rate_gbp", "Tarifa diaria de ingeniería MLOps", "£/día", "itjobswatch UK MLOps (6 meses a 27-10-2026): p10 £425, mediana £550, p90 £775", False),
    ("ttr_reduction", "Reducción del TTR", "fracción", "Caso PIA (15 %)", True),
    ("premium_rate", "Recargo sobre suscripción", "fracción", "Caso PIA (20 %)", True),
    ("peak_concurrency", "Llamadas concurrentes objetivo", "llamadas", "Caso PIA (KPI 1.500)", True),
    ("capex_reserve", "Reserva de contingencia sobre el CAPEX", "fracción", "Supuesto: 10 % del BAC (línea base EVM del caso)", False),
    ("capex_m1", "CAPEX ejecutado en el mes 1", "fracción", "PV acumulada del EVM a la semana 4 (35,33 %)", False),
    ("capex_m2", "CAPEX ejecutado en el mes 2", "fracción", "PV semanas 5-8 del EVM (43,42 %)", False),
    ("capex_m3", "CAPEX ejecutado en el mes 3", "fracción", "PV semanas 9-12 del EVM (21,25 %)", False),
    ("golive_month", "Mes de puesta en producción", "mes", "Supuesto: integración de 12 semanas (meses 1-3)", False),
    ("ramp_start", "Inicio de la adopción comercial", "mes", "Supuesto", False),
    ("ramp_end", "Fin de la rampa de adopción", "mes", "Supuesto: lineal de 10 % a 100 % del objetivo", False),
    ("licensed_seats", "Puestos licenciados que atienden la voz", "puestos", "Supuesto: 1.500 concurrentes con ocupación ≈ 75 %", False),
    ("adoption", "Adopción del módulo (fracción de puestos)", "fracción", "Supuesto (no informado por Alloxentric)", False),
    ("seat_price_gbp", "Precio base mensual por puesto", "£/puesto/mes", "Supuesto (no informado); ver punto de equilibrio", False),
    ("business_share", "Concurrencia media en horario hábil / pico", "fracción", "Supuesto (12 h/día)", False),
    ("offhours_share", "Concurrencia media fuera de horario / pico", "fracción", "Supuesto (12 h/día)", False),
    ("aht_min", "Tiempo medio de manejo (AHT)", "min", "CCMA Benchmark 2025: 9 min 13 s", False),
    ("calls_per_replica", "Llamadas por réplica de 1 vCPU", "llamadas", "Base: tope documentado por el equipo (180, EVIDENCIA.md); pesimista: capacidad estable reproducida (100)", False),
    ("redundancy", "Réplicas de redundancia", "réplicas", "Diseño del equipo: N+1", False),
    ("min_replicas", "Réplicas mínimas", "réplicas", "Alta disponibilidad: mínimo 2 (rango del equipo 1–10)", False),
    ("vcpu_per_replica", "vCPU por réplica", "vCPU", "Diseño del equipo", False),
    ("gib_per_replica", "Memoria por réplica", "GiB", "Supuesto (perfil 1 vCPU / 2 GiB)", False),
    ("audio_mb_per_min", "Audio almacenado por minuto", "MB/min", "Supuesto: G.711 a 64 kbit/s", False),
    ("audio_retention_days", "Retención de grabaciones", "días", "Política de la PoC (UK GDPR)", False),
    ("msgs_per_call", "Mensajes Service Bus por llamada", "mensajes", "Supuesto", False),
    ("tokens_in", "Tokens de entrada por llamada (Azure OpenAI)", "tokens", "Supuesto: una explicación por llamada", False),
    ("tokens_out", "Tokens de salida por llamada", "tokens", "Supuesto", False),
    ("kb_per_call", "Datos derivados por llamada", "KB", "Supuesto (rasgos + resultado causal)", False),
    ("retention_months", "Retención de datos derivados", "meses", "Supuesto", False),
    ("writes_per_call", "Escrituras Blob por llamada", "ops", "Supuesto", False),
    ("log_gb_month", "Telemetría ingerida", "GB/mes", "Supuesto (5 GB/mes gratuitos)", False),
    ("sb_premium_mu", "Unidades Service Bus Premium", "MU", "Arquitectura objetivo: Private Endpoints exigen Premium (con Premium no se cobra Standard)", False),
    ("apim_units", "Unidades APIM Standard v2", "unidades", "Arquitectura objetivo: gateway dedicado con soporte WebSocket", False),
    ("mlops_hours_month", "Horas MLOps mensuales de operación", "h/mes", "Supuesto (recalibración, monitoreo, soporte)", False),
    ("cloud_opex_factor", "Factor sobre costo cloud", "factor", "Supuesto de escenario", False),
    ("discount_annual", "Tasa de descuento anual", "fracción", "Damodaran ene-2026, Europa, Software (System & Application) 8,70 % + 3,3 pp", False),
]
REF = {}
for i, (key, label, unit, src, case) in enumerate(ROWS, start=5):
    vals = [M.params(n)[key] for n in NAMES]
    ws.append([label, *vals, unit, src])
    for col in "BCD":
        ws[f"{col}{i}"].fill = fill_case if case else fill_in
    REF[key] = i
r = len(ROWS) + 6
ws[f"A{r}"] = "Derivados"
ws[f"A{r}"].font = Font(bold=True, color=NAVY)
derived = [
    ("tarifa_h", "Tarifa por hora (día de 7,5 h)", "=({c}{day})/7.5", "£/h"),
    ("capex_total", "CAPEX total (con reserva)", "={c}{hh}*{c}{tarifa_h}*(1+{c}{res})", "£"),
    ("calls_full", "Llamadas/mes con 100 % de los puestos", "={c}{peak}*({c}{bs}+{c}{os})*(60/{c}{aht})*365", "llamadas"),
    ("replicas_peak", "Réplicas en el pico de 1.500 llamadas", "=MAX({c}{minr},CEILING({c}{peak}/{c}{cap},1)+{c}{red})", "réplicas"),
    ("replica_h_price", "Precio por réplica-hora", "=3600*({c}{vcpu}*'Precios Azure'!$C$3+{c}{gib}*'Precios Azure'!$C$4)", "£/h"),
    ("rm", "Tasa de descuento mensual", "=(1+{c}{disc})^(1/12)-1", "fracción"),
]
for j, (key, label, f, unit) in enumerate(derived, start=r + 1):
    row = [label]
    for n in NAMES:
        c = COLS[n]
        row.append(f.format(c=c, day=REF["day_rate_gbp"], hh=REF["capex_hh"], tarifa_h=r + 1, peak=REF["peak_concurrency"],
                            bs=REF["business_share"], os=REF["offhours_share"], aht=REF["aht_min"], minr=REF["min_replicas"], cap=REF["calls_per_replica"], red=REF["redundancy"],
                            vcpu=REF["vcpu_per_replica"], gib=REF["gib_per_replica"], disc=REF["discount_annual"], res=REF["capex_reserve"]))
    ws.append(row + [unit])
    REF[key] = j
ws.column_dimensions["A"].width = 46
for col in "BCD":
    ws.column_dimensions[col].width = 13
ws.column_dimensions["E"].width = 13
ws.column_dimensions["F"].width = 90

# ---------------------------------------------------------------- precios
wp = wb.create_sheet("Precios Azure")
wp.append(["Medidor (uksouth, lista minorista)", "USD", "GBP", "Unidad", "Fuente"])
for c in wp[1]:
    c.font, c.fill = hdr, fill_h
wp.append(["Tipo de cambio implícito GBP/USD", "", M.FX_GBP_PER_USD, "GBP por USD",
           "Lista GBP de Azure: Service Bus Premium 0,70/0,9275 = APIM Standard v2 0,7237/0,9589"])
PR = {}
labels = {"aca_vcpu_s": ("Container Apps consumo — vCPU activa", "1 segundo"), "aca_mem_gib_s": ("Container Apps consumo — memoria activa", "1 GiB-segundo"),
          "acr_basic_day": ("Container Registry Basic", "1 día"), "sb_std_base_month": ("Service Bus Standard — unidad base", "1 mes"),
          "sb_std_ops_m_13_100": ("Service Bus Standard — operaciones 13M–100M", "1 millón"),
          "sb_premium_mu_h": ("Service Bus Premium — unidad de mensajería", "1 hora"), "apim_std_v2_unit_h": ("API Management Standard v2 — unidad", "1 hora"),
          "aoai_4o_mini_in_1k": ("Azure OpenAI gpt-4o-mini (global) — entrada", "1K tokens"), "aoai_4o_mini_out_1k": ("Azure OpenAI gpt-4o-mini (global) — salida", "1K tokens"),
          "blob_hot_lrs_gb_month": ("Blob Storage Hot LRS — almacenamiento", "1 GB/mes"), "blob_hot_write_10k": ("Blob Storage Hot LRS — escrituras", "10K ops"),
          "log_analytics_gb": ("Log Analytics — ingesta", "1 GB")}
for k, (lab, unit) in labels.items():
    row = wp.max_row + 1
    wp.append([lab, M.USD[k], f"=B{row}*$C$2", unit, "https://prices.azure.com/api/retail/prices (consultado 27-10-2026)"])
    PR[k] = f"'Precios Azure'!$C${row}"
for col, w in zip("ABCDE", (52, 12, 12, 12, 62)):
    wp.column_dimensions[col].width = w

# ---------------------------------------------------------------- flujos
HEAD = ["Mes", "CAPEX", "Curva adopción", "Puestos con módulo", "Uso relativo", "En operación", "Réplicas horario hábil",
        "Réplicas fuera de horario", "API inferencia", "Jobs batch", "Service Bus Std", "Service Bus Premium", "APIM",
        "Azure OpenAI", "Blob (audio + resultados)", "Container Registry", "Log Analytics", "MLOps", "OPEX total",
        "Ingresos (recargo)", "Flujo neto", "Flujo acumulado"]
RES = {}
for n in NAMES:
    c = COLS[n]
    S = lambda k: f"Supuestos!${c}${REF[k]}"  # noqa: E731
    w = wb.create_sheet(f"Flujo {n}")
    w.append(HEAD)
    for cell in w[1]:
        cell.font, cell.fill = hdr, fill_h
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for m in range(1, 37):
        i = m + 1
        f_ = S("cloud_opex_factor")

        def rep(share):
            conc = f"{S('peak_concurrency')}*{share}*E{i}"
            return (f"=IF({conc}>0,MAX({S('min_replicas')},CEILING({conc}/{S('calls_per_replica')},1)+{S('redundancy')}),"
                    f"{S('min_replicas')})")
        calls = f"{S('calls_full')}*E{i}"
        w.append([
            m,
            f"=IF(A{i}=1,{S('capex_m1')},IF(A{i}=2,{S('capex_m2')},IF(A{i}=3,{S('capex_m3')},0)))*{S('capex_total')}",
            f"=IF(A{i}<{S('ramp_start')},0,IF(A{i}>={S('ramp_end')},1,0.1+0.9*(A{i}-{S('ramp_start')})/({S('ramp_end')}-{S('ramp_start')})))",
            f"={S('licensed_seats')}*{S('adoption')}*C{i}",
            f"=IF(F{i}=0,0,IF(D{i}=0,0.05*{S('adoption')},D{i}/{S('licensed_seats')}))",
            f"=IF(A{i}>={S('golive_month')},1,0)",
            rep(S('business_share')),
            rep(S('offhours_share')),
            f"=F{i}*{f_}*(G{i}+H{i})*365*{S('replica_h_price')}",
            f"=F{i}*{f_}*60*{S('replica_h_price')}",
            f"=F{i}*{f_}*IF({S('sb_premium_mu')}=0,1,0)*({PR['sb_std_base_month']}+MAX(0,{calls}*{S('msgs_per_call')}/1000000-13)*{PR['sb_std_ops_m_13_100']})",
            f"=F{i}*{f_}*{S('sb_premium_mu')}*730*{PR['sb_premium_mu_h']}",
            f"=F{i}*{f_}*{S('apim_units')}*730*{PR['apim_std_v2_unit_h']}",
            f"=F{i}*{f_}*{calls}*({S('tokens_in')}/1000*{PR['aoai_4o_mini_in_1k']}+{S('tokens_out')}/1000*{PR['aoai_4o_mini_out_1k']})",
            f"=F{i}*{f_}*(({calls}*{S('aht_min')}*{S('audio_mb_per_min')}/1000*{S('audio_retention_days')}/30.4"
            f"+{calls}*{S('kb_per_call')}/1000000*{S('retention_months')})*{PR['blob_hot_lrs_gb_month']}"
            f"+{calls}*{S('writes_per_call')}/10000*{PR['blob_hot_write_10k']})",
            f"=F{i}*{f_}*30.4*{PR['acr_basic_day']}",
            f"=F{i}*{f_}*MAX(0,{S('log_gb_month')}-5)*{PR['log_analytics_gb']}",
            f"=F{i}*{S('mlops_hours_month')}*{S('tarifa_h')}",
            f"=SUM(I{i}:R{i})",
            f"=D{i}*{S('seat_price_gbp')}*{S('premium_rate')}",
            f"=T{i}-S{i}-B{i}",
            f"=SUM($U$2:U{i})",
        ])
    for col in range(2, 23):
        for row in range(2, 38):
            w.cell(row=row, column=col).number_format = "#,##0.00" if col in (3, 5) else "#,##0"
    w.column_dimensions["A"].width = 6
    for col in range(2, 23):
        w.column_dimensions[get_column_letter(col)].width = 13
    w.freeze_panes = "B2"
    RES[n] = (w.title, c)

# ---------------------------------------------------------------- resultados
wr = wb.create_sheet("Resultados", 1)
wr.append(["Indicador", *NAMES, "Fórmula"])
for cell in wr[1]:
    cell.font, cell.fill = hdr, fill_h
rows = [
    ("CAPEX (£)", lambda t, c: f"=Supuestos!{c}{REF['capex_total']}", "HH × tarifa por hora"),
    ("VAN 36 meses (£)", lambda t, c: f"=NPV(Supuestos!{c}{REF['rm']},'{t}'!U2:U37)", "VNA(tasa mensual; flujos netos meses 1-36)"),
    ("TIR mensual", lambda t, c: f"=IFERROR(IRR('{t}'!U2:U37),\"No existe\")", "TIR de los flujos mensuales"),
    ("TIR anual equivalente", lambda t, c: f"=IFERROR((1+IRR('{t}'!U2:U37))^12-1,\"No existe\")", "(1+TIR mensual)^12 − 1"),
    ("Mes de recuperación (payback simple)", lambda t, c: f"=IFERROR(INDEX('{t}'!A2:A37,MATCH(TRUE,INDEX('{t}'!V2:V37>=0,0),0)),\"No recupera\")",
     "Primer mes con flujo acumulado ≥ 0"),
    ("VP ingresos (£)", lambda t, c: f"=NPV(Supuestos!{c}{REF['rm']},'{t}'!T2:T37)", ""),
    ("VP costos CAPEX + OPEX (£)", lambda t, c: f"=NPV(Supuestos!{c}{REF['rm']},'{t}'!B2:B37)+NPV(Supuestos!{c}{REF['rm']},'{t}'!S2:S37)", ""),
    ("Relación B/C", lambda t, c: f"={get_column_letter(NAMES.index(next(k for k, v in RES.items() if v[1] == c)) + 2)}7/"
                                    f"{get_column_letter(NAMES.index(next(k for k, v in RES.items() if v[1] == c)) + 2)}8", "VP ingresos / VP costos"),
    ("OPEX mes 36 (£)", lambda t, c: f"='{t}'!S37", ""),
    ("Ingreso mes 36 (£)", lambda t, c: f"='{t}'!T37", ""),
]
for label, fn, desc in rows:
    wr.append([label, *[fn(*RES[n]) for n in NAMES], desc])
for row in wr.iter_rows(min_row=2, max_row=wr.max_row, min_col=2, max_col=4):
    for cell in row:
        cell.number_format = "#,##0.00"
for rr in (4, 5):
    for col in "BCD":
        wr[f"{col}{rr}"].number_format = "0.0%"
wr.column_dimensions["A"].width = 40
for col in "BCD":
    wr.column_dimensions[col].width = 16
wr.column_dimensions["E"].width = 48

# ---------------------------------------------------------------- sensibilidad (valores calculados)
res = json.loads((Path(__file__).parent / "out" / "results.json").read_text(encoding="utf-8"))
wsn = wb.create_sheet("Sensibilidad")
wsn.append(["Sensibilidad del VAN — escenario Base (valores calculados con model.py; variación ±20 % de cada variable)"])
wsn["A1"].font = Font(bold=True, color=NAVY)
wsn.append(["Variable", "VAN con −20 % (£)", "VAN con +20 % (£)", "Rango (£)"])
for cell in wsn[2]:
    cell.font, cell.fill = hdr, fill_h
for t in res["tornado_base"]:
    wsn.append([t["variable"], round(t["van_-20"]), round(t["van_+20"]), round(t["rango"])])
wsn.append([])
wsn.append(["Punto de equilibrio (VAN = 0)", "Valor"])
wsn.append(["Precio base por puesto, escenario Base (£/mes)", round(res["punto_equilibrio_precio_puesto_base"], 2)])
wsn.append(["Adopción mínima, escenario Base", round(res["punto_equilibrio_adopcion_base"], 4)])
wsn.append(["Precio base por puesto, escenario Pesimista (£/mes)", round(res["punto_equilibrio_precio_puesto_pesimista"], 2)])
wsn.append([])
wsn.append(["Tasa de descuento anual", "VAN Base (£)"])
for k, v in res["sensibilidad_descuento"].items():
    wsn.append([float(k), round(v)])
wsn.column_dimensions["A"].width = 52
for col in "BCD":
    wsn.column_dimensions[col].width = 18

wb.save(OUTFILE)
print("ok", OUTFILE)
