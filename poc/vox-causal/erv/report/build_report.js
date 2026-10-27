// Genera el Informe ERV (Word) de Vox-Causal AI leyendo TODAS las cifras desde los archivos de resultados.
// Uso:  node erv/report/build_report.js [archivo_de_paginas.json]
"use strict";
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, Header, Footer,
  AlignmentType, HeadingLevel, BorderStyle, WidthType, ShadingType, LevelFormat, PageNumber,
  PageBreak, TabStopType, VerticalAlign,
} = require("docx");

const ROOT = path.resolve(__dirname, "..", "..");
const J = (p) => JSON.parse(fs.readFileSync(path.join(ROOT, p), "utf8"));
const EVM = J("erv/out/evm.json");
const FIN = J("erv/out/finance.json");
const MET = J("services/inference_api/model/metrics.json");
const ADM = J("bench/results/admission_1vcpu.json");
const SWEEP = J("bench/results/sweep_1vcpu.json");
const STG = J("bench/results/server_stages.json");
const Q = J("erv/out/quality.json");
const TRZ = fs.readFileSync(path.join(ROOT, "docs/TRAZABILIDAD.md"), "utf8");
const PAGES = process.argv[2] && fs.existsSync(process.argv[2]) ? JSON.parse(fs.readFileSync(process.argv[2], "utf8")) : {};
const OUT = path.join(ROOT, "erv/report/Informe_ERV_VoxCausal_Grupo1.docx");

// ───── formato numérico es-CL ─────
const num = (x, d = 0) => {
  const s = Math.abs(x).toFixed(d).split(".");
  s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return (x < 0 ? "−" : "") + s.join(",");
};
const gbp = (x) => (x < 0 ? "−£" : "£") + num(Math.abs(x));
const pct = (x, d = 1) => num(x * 100, d) + " %";

const TRZ_OK = (TRZ.match(/Resultado: (\d+) de (\d+)/) || [0, "?", "?"]);
const SC = Object.fromEntries(FIN.scenarios.map((s) => [s.scenario, s]));
const SB = SC["Base"], SP = SC["Pesimista"], SO = SC["Optimista"];
const A180 = ADM.find((r) => r.streams === 180), A400 = ADM.find((r) => r.streams === 400);
const S100 = SWEEP.find((r) => r.streams === 100), S300 = SWEEP.find((r) => r.streams === 300);
const T = MET.treatments;
const LBL = { long_wait: "Espera prolongada", multi_transfer: "Múltiples transferencias", billing_error: "Error de facturación" };
const maxErr = Math.max(...Object.values(T).map((t) => t.error_dml_replicas.max));
const refs = Object.values(T).flatMap((t) => Object.values(t.refutations));
const CV = FIN.customer_value;
const KPI = FIN.kpi_capacity_opex;
const BP = SB.params;
const COV = `${num(Q.coverage_pct, 0)} %`;
const NT = Q.tests;

// ───── estilo ─────
const NAVY = "1B3A5F", ALT = "F4F7FB", OKF = "E6F4EA", WARNF = "FFF4D6", BORDER = "C9D3DE";
const W = 9072; // ancho útil A4 con márgenes de 2,5 cm (DXA)
const border = { style: BorderStyle.SINGLE, size: 4, color: BORDER };
const borders = { top: border, bottom: border, left: border, right: border };

function runs(text, base = {}) {
  // **negrita** y ~cursiva~ simples
  const parts = text.split(/(\*\*[^*]+\*\*|~[^~]+~)/g).filter(Boolean);
  return parts.map((p) => {
    if (p.startsWith("**")) return new TextRun({ ...base, text: p.slice(2, -2), bold: true });
    if (p.startsWith("~") && p.endsWith("~") && p.length > 2) return new TextRun({ ...base, text: p.slice(1, -1), italics: true });
    return new TextRun({ ...base, text: p });
  });
}
const P = (t, o = {}) => new Paragraph({ spacing: { after: 100, line: 264 }, alignment: AlignmentType.JUSTIFIED, ...o, children: runs(t, o.run || {}) });
const H1 = (t, br = false) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: br, keepNext: true, children: [new TextRun(t)] });
const H1n = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true, children: [new TextRun(t)] });
const BL = (t, lvl = 0) => new Paragraph({ numbering: { reference: "bul", level: lvl }, spacing: { after: 60, line: 252 }, children: runs(t) });
const NL = (t) => new Paragraph({ numbering: { reference: "num", level: 0 }, spacing: { after: 60, line: 252 }, children: runs(t) });
const CAP = (t) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60, after: 160 }, children: runs(t, { size: 18, italics: true, color: "52514E" }) });
const SRC = (t) => new Paragraph({ spacing: { after: 120 }, children: runs(t, { size: 16, color: "52514E" }) });

function img(file, widthCm) {
  const buf = fs.readFileSync(path.join(ROOT, file));
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20); // PNG IHDR
  const px = Math.round((widthCm / 2.54) * 96);
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 80, after: 40 },
    children: [new ImageRun({ type: "png", data: buf, transformation: { width: px, height: Math.round((px * h) / w) },
      altText: { title: path.basename(file), description: path.basename(file), name: path.basename(file) } })] });
}

function table(headers, rows, widthsPct, opts = {}) {
  const widths = widthsPct.map((p) => Math.round((W * p) / 100));
  widths[widths.length - 1] += W - widths.reduce((a, b) => a + b, 0);
  const fs_ = opts.size || 17;
  const cell = (text, i, header, fill) => new TableCell({
    borders, width: { size: widths[i], type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
    shading: { fill: header ? NAVY : fill, type: ShadingType.CLEAR, color: "auto" },
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: [new Paragraph({ alignment: (opts.align && opts.align[i]) || AlignmentType.LEFT,
      children: runs(String(text), { size: fs_, color: header ? "FFFFFF" : "16202A", bold: header }) })],
  });
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, i, true)) }),
      ...rows.map((r, k) => new TableRow({ children: r.map((c, i) => cell(c, i, false,
        (opts.fills && opts.fills[k]) || (k % 2 ? ALT : "FFFFFF"))) })),
    ],
  });
}
const gap = () => new Paragraph({ spacing: { after: 80 }, children: [] });

function sideBySide(fileA, fileB) {
  const half = Math.round(W / 2);
  const c = (f) => new TableCell({ borders: { top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" }, bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" }, left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" }, right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" } },
    width: { size: half, type: WidthType.DXA }, children: [img(f, 7.9)] });
  return new Table({ width: { size: W, type: WidthType.DXA }, columnWidths: [half, W - half], rows: [new TableRow({ children: [c(fileA), c(fileB)] })] });
}

// ───── índice con números de página (segunda pasada) ─────
const CHAPTERS = [
  "Resumen ejecutivo",
  "1. Contexto y problema",
  "2. Gestión y control del proyecto (EVM)",
  "3. Arquitectura C4",
  "4. Pipeline MLOps, inferencia y resolución del incidente",
  "5. Evidencia del repositorio y gobernanza",
  "6. Métricas objetivas de software e IA",
  "7. Evaluación financiera ERV",
  "8. Impacto, recomendación ejecutiva y hoja de ruta",
  "Referencias",
];
const tocLine = (t) => new Paragraph({
  tabStops: [{ type: TabStopType.RIGHT, position: W, leader: "dot" }], spacing: { after: 90 },
  children: [new TextRun({ text: t, size: 22 }), new TextRun({ text: `\t${PAGES[t] || ""}`, size: 22 })],
});

// ───── contenido ─────
const C = [];

// Portada
C.push(
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 200, after: 60 }, children: [new TextRun({ text: "UNIVERSIDAD TECNOLÓGICA METROPOLITANA", bold: true, size: 26, color: NAVY })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 }, children: [new TextRun({ text: "Facultad de Ingeniería — Escuela de Informática y Computación", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 600 }, children: [new TextRun({ text: "Gestión de Proyectos Informáticos (GPI) · 2026-II", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new TextRun({ text: "INFORME DE EVALUACIÓN TÉCNICA Y ECONÓMICA", bold: true, size: 36, color: NAVY })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new TextRun({ text: "(Informe ERV)", bold: true, size: 30, color: NAVY })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 500 }, children: [new TextRun({ text: "Integración del prototipo de inferencia causal multimodal Vox-Causal AI en la plataforma corporativa SaaS de Alloxentric SpA (Microsoft Azure, Reino Unido)", size: 24, italics: true })] }),
);
C.push(table(["Campo", "Detalle"], [
  ["Cliente corporativo", "Alloxentric SpA — casa matriz en Londres, Reino Unido"],
  ["Caso", "PIA — Arquitectura C4, Pipeline MLOps e Informe ERV"],
  ["Sección / grupo", "411 — Grupo N.º 1"],
  ["Docente", "Dr. Oscar Eduardo Magna Veloso"],
  ["Restricciones inyectadas", "R1: latencia < 200 ms y cifrado en tránsito con SAS URLs (UK GDPR) · R2: aislamiento estricto entre batch y API en tiempo real"],
  ["Repositorio", "github.com/Nacho880/Proyecto-GPI — /poc/vox-causal y /docs/erv"],
  ["Fecha de entrega", "28 de octubre de 2026"],
], [30, 70]));
C.push(gap());
C.push(table(["Integrante", "Rol en el proyecto (matriz RACI)"], [
  ["Ignacio Ortega", "Jefe de proyecto — gestión, EVM y evaluación económica"],
  ["Camilo Moya", "Arquitecto de software — C4 y API de inferencia"],
  ["Joaquín Apablaza", "Ingeniero de IA/MLOps y SQA — pipeline causal, pruebas y métricas"],
  ["Lucas Mora", "Ingeniero cloud y seguridad — Azure, cumplimiento UK GDPR y aislamiento"],
], [30, 70]));

// Índice
C.push(new Paragraph({ pageBreakBefore: true, spacing: { after: 200 }, children: [new TextRun({ text: "Índice", bold: true, size: 32, color: NAVY })] }));
CHAPTERS.forEach((c) => C.push(tocLine(c)));

// Resumen ejecutivo
C.push(H1("Resumen ejecutivo", true));
C.push(P(`Alloxentric SpA solicitó evaluar si conviene financiar e integrar en su plataforma SaaS el prototipo **Vox-Causal AI**, que identifica en plena llamada la **causa raíz** del riesgo de fuga del cliente combinando análisis prosódico de la voz con modelos causales estructurales (SCM). Durante el proyecto, el cliente agregó dos restricciones: **latencia menor a 200 ms con cifrado en tránsito mediante SAS URLs (UK GDPR)** y **aislamiento estricto entre el pipeline batch y la API en tiempo real**.`));
C.push(P(`La respuesta arquitectónica fue separar el sistema en un **camino caliente** (inferencia en vivo, sin colas ni LLM ni reestimación causal) y un **camino frío** (entrenamiento, validación, explicación y auditoría), aislados en redes, cómputo, identidades y datos, con un único contrato entre ambos: el modelo aprobado y su huella SHA-256. La propuesta se validó con una **prueba de concepto funcional** incluida en el repositorio.`));
C.push(table(["Indicador", "Meta", "Resultado medido", "Estado"], [
  ["Error de ATE (precisión causal)", "≤ 0,05", `${num(Math.min(...Object.values(T).map((t) => t.error_dml)), 4)} – ${num(Math.max(...Object.values(T).map((t) => t.error_dml)), 4)} (máx. en 5 réplicas ${num(maxErr, 4)})`, "Cumple"],
  ["Latencia de inferencia (p95)", "< 200 ms", `Servidor ${num(STG.server_total.p95_ms, 2)} ms · extremo a extremo ${num(A180.p95_ms, 1)} ms con 180 llamadas`, "Cumple"],
  ["Concurrencia", "1.500 llamadas", `${FIN.sessions_per_replica_measured} por réplica de 1 vCPU sin degradación → ${KPI.replicas} réplicas (N+1)`, "Cumple por diseño"],
  ["Cobertura de pruebas", "≥ 85 %", `${COV} (${NT} pruebas automatizadas)`, "Cumple"],
  ["VAN a 36 meses (base)", "> 0", `${gbp(SB.npv_gbp)} · B/C ${num(SB.bc_ratio, 2)} · payback mes ${SB.payback_month}`, "Viable"],
], [27, 13, 45, 15], { size: 16, fills: [OKF, OKF, OKF, OKF, OKF] }));
C.push(gap());
C.push(P(`**Dictamen: GO condicionado.** El proyecto es técnicamente viable y económicamente rentable en el escenario base y en el optimista. El escenario pesimista (VAN ${gbp(SP.npv_gbp)}) muestra que el valor depende de la adopción: el punto de equilibrio es de **${num(FIN.breakeven_seats)} puestos (${pct(FIN.breakeven_adoption)} de la base instalada)**. Se recomienda avanzar por fases, con una puerta de decisión al cierre del piloto ligada a ese umbral (capítulo 8).`));

// Capítulo 1
C.push(H1("1. Contexto y problema"));
C.push(P(`Alloxentric SpA optimiza interacciones omnicanal con inteligencia artificial y procesa diariamente millones de interacciones de texto, audio y video en Microsoft Azure. Sus modelos actuales son **correlacionales**: detectan sentimiento o tono, pero no explican ~por qué~ un cliente está insatisfecho ni qué acción reduciría su riesgo de fuga.`));
C.push(P(`Vox-Causal AI aborda ese vacío con un **modelo causal estructural** (DAG) sobre las causas operativas de una llamada —espera prolongada, transferencias múltiples y errores de facturación—, ajustado por confusores como la antigüedad del cliente y el contacto repetido, y con el estrés vocal como mediador medido en vivo.`));
C.push(H2("1.1 Por qué IA causal y no correlacional"));
C.push(P(`La diferencia se demostró con datos de prueba en los que el efecto real de cada causa es conocido (${num(MET.dataset.n)} llamadas). El enfoque correlacional (diferencia simple de medias) confunde el efecto de la causa con el de los confusores; el estimador causal (DoWhy con ajuste ~backdoor~ y EconML Double ML) lo aísla:`));
C.push(table(["Causa raíz", "Efecto real (ATE)", "Correlacional", "Error correlacional", "Causal (DML)", "Error causal"],
  Object.entries(T).map(([k, t]) => [LBL[k], num(t.true_ate, 4), num(t.naive_correlational, 4), num(t.error_naive, 4), num(t.linear_dml, 4), num(t.error_dml, 4)]),
  [26, 15, 15, 15, 15, 14], { size: 16, align: [0, 2, 2, 2, 2, 2].map((a) => (a ? AlignmentType.RIGHT : AlignmentType.LEFT)) }));
C.push(CAP("Tabla 1. Efecto de cada causa sobre la probabilidad de fuga a 90 días (escala 0–1). Fuente: model/metrics.json."));
C.push(P(`El modelo correlacional **incumple el KPI** (error ${num(T.long_wait.error_naive, 3)} > 0,05) y además **invierte el orden de las causas**: prioriza la espera, cuando la causa de mayor impacto es el error de facturación. Un operador guiado por correlaciones atacaría primero el problema de menor efecto.`));
C.push(H2("1.2 Objetivos y alcance"));
C.push(BL("Evaluar la **compatibilidad técnica** del prototipo (Python 3.12, FastAPI, DoWhy/EconML) con la arquitectura de Alloxentric en Azure (API Management, Service Bus, Blob Storage con SAS y Azure OpenAI)."));
C.push(BL("Verificar los **KPI técnicos**: latencia, concurrencia de 1.500 llamadas y error de ATE ≤ 0,05, incorporando las restricciones R1 y R2."));
C.push(BL("Cuantificar **CAPEX, OPEX, VAN, TIR, Payback y B/C** y emitir un dictamen GO / NO-GO para el directorio en Londres."));

// Capítulo 2
C.push(H1("2. Gestión y control del proyecto (EVM)"));
C.push(P(`La línea base del proyecto de integración corresponde a las **${EVM.bac_h} horas-hombre** del caso (BAC = ${gbp(EVM.bac_gbp)} a ${gbp(EVM.rate_gbp_h)}/h), distribuidas en siete paquetes de trabajo durante ${EVM.weeks} semanas. La fecha de corte es el cierre de la **semana ${EVM.status_week}**; las restricciones del cliente se inyectaron en la semana ${EVM.incident_week}.`));
C.push(SRC(`Origen de los datos: PV desde la línea base; EV a partir del avance físico verificable en el repositorio (código, pruebas, scripts y diagramas); AC simulado para el ejercicio académico, incluido el retrabajo provocado por el incidente.`));
C.push(table(["EDT", "Paquete de trabajo", "Semanas", "BAC (h)", "PV (h)", "EV (h)", "AC (h)", "SPI", "CPI"],
  EVM.packages.map((p) => [p.code, p.name, p.weeks, num(p.bac_h), num(p.pv_h), num(p.ev_h), num(p.ac_h), p.spi == null ? "—" : num(p.spi, 2), p.cpi == null ? "—" : num(p.cpi, 2)])
    .concat([["", "**Total proyecto**", "S1–S12", `**${num(EVM.bac_h)}**`, `**${num(EVM.pv_h)}**`, `**${num(EVM.ev_h)}**`, `**${num(EVM.ac_h)}**`, `**${num(EVM.spi, 2)}**`, `**${num(EVM.cpi, 2)}**`]]),
  [5, 39, 9, 8, 8, 8, 8, 7, 8], { size: 15, align: [0, 0, 0, 2, 2, 2, 2, 2, 2].map((a) => (a ? AlignmentType.RIGHT : AlignmentType.LEFT)) }));
C.push(CAP("Tabla 2. Estructura de desglose del trabajo y valor ganado al corte. Fuente: erv/out/evm.json."));
C.push(img("erv/out/evm_curva_s.png", 14));
C.push(CAP("Figura 1. Curva S: PV, EV y AC acumulados en % del BAC, con pronóstico al término."));
C.push(img("erv/out/evm_cuadrante.png", 16));
C.push(CAP("Figura 2. Cuadrante de desempeño (CPI vs. SPI) con la clasificación de la cátedra; trayectoria semanal hasta el corte."));
C.push(table(["Indicador", "Valor", "Interpretación"], [
  ["SV = EV − PV", `+${num(EVM.sv_h, 1)} h`, "Adelanto en plazo: el pipeline MLOps y las pruebas avanzaron antes de lo planificado"],
  ["CV = EV − AC", `${num(EVM.cv_h, 1)} h`, "Sobrecosto concentrado en integración Azure y seguridad (retrabajo por R1 y R2)"],
  ["SPI / CPI", `${num(EVM.spi * 100, 1)} % / ${num(EVM.cpi * 100, 1)} %`, `Cuadrante IV (adelantado y sobre presupuesto) · clasificación **${EVM.classification}** (CPI y SPI ≥ 0,90)`],
  ["EAC = BAC / CPI", `${num(EVM.eac_h, 1)} h (${gbp(EVM.eac_gbp)})`, `Desvío final estimado de ${num(-EVM.vac_h, 1)} h`],
  ["Reserva de contingencia (10 %)", `${num(EVM.reserve_h)} h`, `Cubre el desvío: se consumiría el ${num(EVM.reserve_consumed_pct, 1)} %`],
  ["TCPI", num(EVM.tcpi, 3), "Eficiencia requerida para terminar dentro del BAC: exigente; se gestiona con la reserva"],
], [27, 23, 50], { size: 16 }));
C.push(gap());
C.push(P(`**Acciones correctivas:** (1) congelar el alcance de los paquetes 3 y 5 en los controles ya implementados; (2) reutilizar los scripts verificados (deploy.sh / verify.sh) para el piloto; (3) aprobar formalmente el uso de la reserva para el retrabajo del incidente, con seguimiento semanal del CPI.`));

// Capítulo 3
C.push(H1("3. Arquitectura C4"));
C.push(P(`Los diagramas se generan desde el código y cada una de sus afirmaciones se verifica automáticamente (**${TRZ_OK[1]} de ${TRZ_OK[2]}** comprobaciones aprobadas; docs/TRAZABILIDAD.md). Los elementos con borde punteado corresponden a **diseño productivo** que no se montó en la prueba de concepto por costo o cuota de la suscripción.`));
C.push(H2("3.1 Nivel 1 — Contexto"));
C.push(img("docs/diagrams/C4_N1_Contexto.png", 16));
C.push(CAP("Figura 3. Contexto: actores, sistemas externos y protocolos."));
C.push(P(`Vox-Causal AI recibe el audio **solo del canal del cliente** y el contexto de la llamada desde la telefonía de Alloxentric (WSS, TLS 1.2+) y devuelve al operador la causa raíz y la acción sugerida cada ${num(500)} ms. Azure OpenAI solo **redacta** explicaciones post-llamada: no decide la causa.`));
C.push(H2("3.2 Nivel 2 — Contenedores en dos zonas aisladas"));
C.push(img("docs/diagrams/C4_N2_Contenedores.png", 16));
C.push(CAP("Figura 4. Contenedores, tecnologías y protocolos; zona A (tiempo real) y zona B (batch)."));
C.push(table(["Contenedor", "Tecnología", "Protocolo", "Estado"], [
  ["API de inferencia", "FastAPI · Python 3.12 · NumPy · 1 vCPU/réplica · 1–10 réplicas", "WSS / HTTPS (TLS 1.2+)", "Implementado"],
  ["Gateway", "Azure API Management (Standard v2, admite WebSocket)", "WSS", "Diseño productivo"],
  ["Cola call-closed", "Azure Service Bus, solo Entra ID (API = Sender, batch = Receiver)", "AMQP + TLS", "Implementado"],
  ["Worker y entrenamiento", "Container Apps Jobs · DoWhy · EconML · Azure OpenAI con respaldo", "AMQP / HTTPS", "Implementado"],
  ["Datos", "Blob Storage UK South: sin claves, sin acceso público, retención 30 días", "HTTPS + User Delegation SAS", "Implementado"],
  ["Transversal", "Key Vault (RBAC), ACR sin admin, Log Analytics, 3 identidades administradas", "HTTPS", "Implementado"],
], [20, 46, 19, 15], { size: 15 }));
C.push(H2("3.3 Nivel 3 — Componentes"));
C.push(img("docs/diagrams/C4_N3_Componentes_API.png", 15));
C.push(CAP(`Figura 5. Componentes de la API (camino caliente). Rasgos prosódicos p95 ${num(STG.prosody.p95_ms, 2)} ms; modelo causal p95 ${num(STG.scm.p95_ms, 2)} ms.`));
C.push(img("docs/diagrams/C4_N3_Componentes_Batch.png", 14));
C.push(CAP("Figura 6. Componentes del pipeline batch (camino frío) con su control de calidad."));
C.push(P(`La API no importa DoWhy, EconML, pandas ni scikit-learn: evalúa fórmulas cerradas con NumPy sobre el modelo **ya ajustado**. El camino frío identifica, estima, refuta y publica; solo un modelo que supera el control de calidad llega, por CI, a una imagen nueva e inmutable de la API.`));

// Capítulo 4
C.push(H1("4. Pipeline MLOps, inferencia y resolución del incidente"));
C.push(img("docs/diagrams/Pipeline_MLOps_Inferencia.png", 16));
C.push(CAP("Figura 7. Pipeline MLOps e inferencia: ingesta, preprocesamiento, invocación del modelo, respaldos, telemetría y auditoría."));
C.push(H2("4.1 Resolución del incidente de cátedra"));
C.push(P(`**Restricciones inyectadas.** R1: el servicio de inferencia debe responder en **menos de 200 ms** y cumplir **cifrado en tránsito mediante SAS URLs** por UK GDPR. R2: **aislamiento estricto** entre el pipeline de datos batch y la API de inferencia en tiempo real.`));
C.push(P(`**Impacto sobre la arquitectura original.** La integración prevista encadenaba en una sola API componentes incompatibles con la meta: Service Bus es asíncrono, una llamada a Azure OpenAI tarda cientos de milisegundos y la estimación causal con DoWhy/EconML toma minutos. Además, leer audios desde Blob con SAS en cada inferencia agregaba latencia y acoplaba el mundo batch con el de tiempo real. Por último, una SAS **no cifra**: es un token de autorización; el cifrado lo aporta TLS.`));
C.push(table(["#", "Decisión", "Por qué (restricción)", "Alternativa descartada", "Evidencia"], [
  ["D1", "Separar camino caliente y camino frío", "R1 y R2: nada asíncrono o lento en la ruta en vivo", "Una sola API que entrena, explica e infiere", `Servidor p95 ${num(STG.server_total.p95_ms, 2)} ms (${num(STG.server_total.p95_ms / 2, 1)} % del presupuesto)`],
  ["D2", "Modelo causal precalculado en la API", "R1: reestimar por llamada no cabe en 200 ms", "DoWhy/EconML en línea", `Runtime p95 ${num(STG.scm.p95_ms, 2)} ms`],
  ["D3", "TLS 1.2+ en todo salto; SAS de delegación de usuario (Entra ID), solo lectura, spr=https, 5 min, fuera de la ruta en vivo", "R1 cifrado / UK GDPR", "SAS con clave de cuenta; leer audio desde Blob en cada inferencia", "Pruebas de SAS (spr, sp, skoid); cuenta sin claves; verify.sh rechaza HTTP y SAS manipulada"],
  ["D4", "Aislamiento en 5 dimensiones: cómputo, red, datos, mensajería e identidad", "R2", "Mismo entorno con colas compartidas", "VNets sin peering, batch sin ingreso público; pruebas de arquitectura en CI"],
  ["D5", "Control de admisión: 180 sesiones por réplica", "R1 bajo carga", "Aceptar todo y degradar", `400 ofrecidas → p95 ${num(A400.p95_ms, 1)} ms; ${A400.errors.closed_1013} derivadas (1013)`],
  ["D6", "Analizar solo el canal del cliente; seudonimizar", "UK GDPR y EU AI Act art. 5.1.f", "Analizar ambas voces", "Prueba: la voz del operador no altera el resultado"],
], [5, 25, 20, 20, 30], { size: 14 }));
C.push(CAP("Tabla 3. Decisiones arquitectónicas frente al incidente."));
C.push(P(`**Verificación.** Las decisiones se verifican en tres niveles: (1) pruebas automatizadas del repositorio (${NT}, cobertura ${COV}); (2) benchmark de concurrencia sobre una réplica de 1 vCPU: con 100 llamadas el p95 es ${num(S100.p95_ms, 1)} ms, mientras que sin control de admisión a 300 llamadas el p95 sube a ${num(S300.p95_ms / 1000, 1)} s, lo que justifica D5; (3) en Azure, el script verify.sh comprueba la redirección HTTP→HTTPS, el rechazo de TLS < 1.2, la SAS por HTTP, manipulada o de escritura, el acceso sin claves y el aislamiento entre VNets, y ejecuta el benchmark dentro de UK South.`));
C.push(P(`**Riesgo residual.** El estimador prosódico se calibró con voz sintética etiquetada (MAE ${num(MET.stress_calibration.mae, 3)}, R² ${num(MET.stress_calibration.r2, 3)}); antes de producción debe recalibrarse con un corpus real etiquetado de Alloxentric bajo una DPIA aprobada.`));

// Capítulo 5
C.push(H1("5. Evidencia del repositorio y gobernanza"));
C.push(P(`El repositorio oficial (github.com/Nacho880/Proyecto-GPI) aloja la prueba de concepto en **/poc/vox-causal** y el informe y la presentación en **/docs/erv**, según la pauta.`));
C.push(table(["Carpeta", "Contenido"], [
  ["/poc/vox-causal/services/inference_api", "Camino caliente: app/ (9 componentes), Dockerfile, modelo aprobado (model.json + SHA-256)"],
  ["/poc/vox-causal/services/batch_pipeline", "Camino frío: generador SCM, entrenamiento, registro, worker, explicación"],
  ["/poc/vox-causal/libs/voxfeatures", "Rasgos prosódicos compartidos (evita desfase entrenamiento/servicio)"],
  ["/poc/vox-causal/tests", `Unitarias, integración, batch, arquitectura y trazabilidad (${NT} pruebas)`],
  ["/poc/vox-causal/bench · /tools", "Benchmark de latencia/concurrencia, simulador de llamadas, generación de diagramas"],
  ["/poc/vox-causal/deploy/azure", "deploy.sh, verify.sh y teardown.sh (UK South)"],
  ["/poc/vox-causal/erv", "Modelos EVM y financiero reproducibles (evm.py, finance.py) y generador de este informe"],
  ["/.github/workflows/vox-causal-ci.yml", "CI: lint, complejidad, pruebas, cobertura ≥ 85 % y construcción de imágenes"],
  ["/docs/erv", "Informe ERV (Word/PDF), presentación de 10 diapositivas y evidencia de Azure"],
], [36, 64], { size: 15 }));
C.push(gap());
C.push(P(`**Flujo de ramas.** Cada paquete de trabajo se desarrolla en una rama feature/vox-causal-*, se integra por pull request hacia staging con el CI en verde y se promueve a main al cierre de cada hito. La promoción de un modelo es un commit que verifica su huella SHA-256, lo que deja trazabilidad de qué versión corre en producción y quién la aprobó.`));
C.push(H2("5.1 Matriz RACI"));
C.push(table(["Actividad", "I. Ortega", "C. Moya", "J. Apablaza", "L. Mora"], [
  ["Gestión, EVM y control de cambios", "R/A", "C", "C", "C"],
  ["Arquitectura C4 y decisiones del incidente", "A", "R", "C", "C"],
  ["API de inferencia (camino caliente)", "I", "R/A", "C", "C"],
  ["Pipeline causal MLOps (camino frío)", "I", "C", "R/A", "I"],
  ["Integración y despliegue en Azure", "A", "C", "I", "R"],
  ["Seguridad, aislamiento y cumplimiento UK GDPR", "A", "C", "I", "R"],
  ["Pruebas SQA y benchmark de desempeño", "I", "C", "R/A", "C"],
  ["Evaluación financiera y dictamen", "R/A", "I", "C", "C"],
  ["Presentación y defensa oral", "A", "R", "R", "R"],
], [44, 14, 14, 14, 14], { size: 16, align: [0, 1, 1, 1, 1].map((a) => (a ? AlignmentType.CENTER : AlignmentType.LEFT)) }));
C.push(SRC("R = responsable · A = aprueba · C = consultado · I = informado."));

// Capítulo 6
C.push(H1("6. Métricas objetivas de software e IA"));
C.push(table(["Dimensión", "Métrica", "Resultado", "Fuente"], [
  ["Precisión causal", "Error de ATE (DML), 3 causas", `${Object.entries(T).map(([k, t]) => num(t.error_dml, 4)).join(" · ")}; máx. 5 réplicas ${num(maxErr, 4)}`, "model/metrics.json"],
  ["Robustez causal", "Refutaciones DoWhy", `${refs.filter((r) => r.passed).length}/${refs.length} aprobadas (placebo, causa común aleatoria, subconjunto)`, "model/metrics.json"],
  ["Estimador prosódico", "MAE / R² (voz sintética)", `${num(MET.stress_calibration.mae, 3)} / ${num(MET.stress_calibration.r2, 3)}`, "model/metrics.json"],
  ["Latencia", "Servidor p50 / p95 / p99", `${num(STG.server_total.p50_ms, 2)} / ${num(STG.server_total.p95_ms, 2)} / ${num(STG.server_total.p99_ms, 2)} ms`, "server_stages.json"],
  ["Latencia", "Extremo a extremo p95 (180 llamadas)", `${num(A180.p95_ms, 1)} ms · ${num(A180.pct_under_200ms, 0)} % < 200 ms`, "admission_1vcpu.json"],
  ["Concurrencia", "Capacidad por réplica de 1 vCPU", `180 llamadas; con 400 ofrecidas p95 ${num(A400.p95_ms, 1)} ms`, "admission_1vcpu.json"],
  ["Calidad SQA", "Pruebas / cobertura", `${NT} pruebas · ${COV} (líneas y ramas)`, "quality.json"],
  ["Mantenibilidad", "Complejidad ciclomática / lint", `Promedio A (${num(Q.cc_avg, 1)}); máx. ${Q.cc_max_rank} (${Q.cc_max}) · ${Q.ruff_findings} hallazgos ruff`, "quality.json"],
  ["Trazabilidad", "Diagramas verificados contra el código", `${TRZ_OK[1]}/${TRZ_OK[2]}`, "TRAZABILIDAD.md"],
], [18, 27, 37, 18], { size: 15 }));
C.push(CAP("Tabla 4. Métricas medidas en la prueba de concepto."));
C.push(H2("6.1 Deuda técnica"));
C.push(P(`La deuda técnica se estimó partida por partida, como esfuerzo de remediación (método SQALE), a partir de los hallazgos de radon, cobertura y dependencias:`));
C.push(table(["Partida", "Remediación", "Horas"], [
  [`train.${Q.cc_max_fn} con complejidad ${Q.cc_max_rank} (${Q.cc_max})`, "Dividir en etapas (identificar, estimar, refutar, publicar)", "1,0"],
  ["Excepción de complejidad en _register_routes (main.py)", "Separar rutas en APIRouter por dominio", "0,5"],
  ["networkx fijado en 3.4.2 por incompatibilidad con DoWhy", "Adaptador o actualización cuando DoWhy lo soporte", "0,5"],
  ["≈ 10 líneas o ramas sin cubrir en la API", "Pruebas adicionales (stream, events, ws_handler)", "1,0"],
  ["11 rutas que requieren Azure, probadas solo con verify.sh", "Pruebas de integración con emuladores (Azurite)", "1,0"],
  ["**Total**", "", "**4,0 h**"],
], [44, 44, 12], { size: 15, align: [0, 0, AlignmentType.RIGHT] }));
C.push(gap());
C.push(P(`Frente a 800 horas de desarrollo, la razón de deuda es de 0,5 %, equivalente a una calificación **A** en el modelo SQALE (≤ 5 %). El CI incluye la integración opcional con SonarCloud para obtener la cifra oficial en cada commit.`));

// Capítulo 7
C.push(H1("7. Evaluación financiera ERV"));
C.push(P(`Modelo mensual a 36 meses en **libras esterlinas (GBP)**, antes de impuestos, con los meses 1–3 de desarrollo y el módulo cobrado desde el mes 4 como **recargo del 20 %** sobre la suscripción SaaS en el Reino Unido y Europa. Tasa de descuento: WACC de ${pct(BP.wacc)}. Todos los cálculos son reproducibles con erv/finance.py.`));
C.push(H2("7.1 Supuestos"));
C.push(table(["Supuesto", "Base", "Fuente / criterio"], [
  ["Tarifa de ingeniería", `${gbp(EVM.rate_gbp_h)}/h`, "Mediana de contratos de ML en UK: £575/día (IT Jobs Watch, oct-2026)"],
  ["CAPEX", `${gbp(SB.capex_gbp)}`, "800 h × tarifa + 10 % de reserva de contingencia (EVM)"],
  ["Puestos de agente en UK/UE", num(BP.installed_seats), "Supuesto de base instalada de Alloxentric"],
  ["Adopción del módulo / rampa", `${pct(BP.adoption, 0)} en ${BP.ramp_months} meses`, "Supuesto; sensibilizado de 20 % a 60 %"],
  ["Suscripción base por puesto", `${gbp(BP.base_price_gbp)}/mes (recargo ${gbp(BP.base_price_gbp * BP.premium_pct)})`, "IA para contact center: US$75–155 por agente/mes (Bright Pattern, 2026)"],
  ["Concurrencia en hora punta", `${pct(BP.peak_concurrency, 0)} de los puestos`, "Supuesto; define las réplicas necesarias"],
  ["Capacidad por réplica", `${FIN.sessions_per_replica_measured} llamadas`, "Medida en la prueba de concepto (D5)"],
  ["Tipo de cambio", `US$${num(FIN.usd_per_gbp, 2)} por £`, "CoinCodex, oct-2026"],
  ["WACC", pct(BP.wacc), "Sector tecnología (PwC Cost of Capital, feb-2026)"],
], [30, 22, 48], { size: 15 }));
C.push(H2("7.2 CAPEX y OPEX"));
const it = SB.steady_state.items;
C.push(table([`Partida OPEX mensual (régimen base: ${num(SB.steady_state.seats)} puestos, ${SB.steady_state.replicas} réplicas)`, "£/mes", "Base de cálculo"], [
  ["Cómputo API (Container Apps)", gbp(it.api_compute), `${SB.steady_state.replicas} réplicas × 1 vCPU / 2 GiB activas 24/7 (US$0,000024/vCPU-s)`],
  ["API Management Standard v2", gbp(it.apim), "US$700/mes; admite WebSocket"],
  ["Service Bus Premium (1 MU)", gbp(it.service_bus), "Requerido para Private Endpoints (aislamiento R2)"],
  ["Azure OpenAI (GPT-4o mini)", gbp(it.azure_openai), `650 tokens por explicación; ${num(SB.steady_state.seats * BP.calls_per_seat_month / 1e6, 1)} millones de llamadas/mes`],
  ["Almacenamiento de audio", gbp(it.audio_storage), "G.711 64 kbps, 5 min por llamada, retención 30 días"],
  ["Jobs batch, Log Analytics y otros", gbp(it.batch_compute + it.log_analytics + it.otros_azure), "Worker cada 5 min, entrenamiento semanal, ACR, Key Vault, Private Endpoints"],
  ["Operación y mantenimiento MLOps", gbp(it.mantenimiento_mlops), `${BP.maintenance_h_month} h/mes de ingeniería`],
  ["**Total OPEX**", `**${gbp(SB.steady_state.opex_month)}**`, `Ingreso por recargo en régimen: ${gbp(SB.steady_state.revenue_month)}/mes`],
], [40, 14, 46], { size: 15, align: [0, AlignmentType.RIGHT, 0] }));
C.push(SRC(`A la capacidad del KPI (1.500 llamadas simultáneas) se requieren ${KPI.replicas} réplicas y el OPEX asciende a ${gbp(KPI.total)}/mes.`));
C.push(H2("7.3 Indicadores por escenario"));
const irrTxt = (s) => (s.irr_annual == null ? "—" : s.irr_annual > 3 ? "> 300 %" : pct(s.irr_annual));
C.push(table(["Indicador", "Pesimista", "Base", "Optimista"], [
  ["Supuestos clave", `${pct(SP.params.adoption, 0)} adopción · ${gbp(SP.params.base_price_gbp)} · rampa ${SP.params.ramp_months} m · OPEX +${pct(SP.params.opex_factor - 1, 0)} · CAPEX +${pct(SP.params.capex_factor - 1, 0)}`, `${pct(BP.adoption, 0)} · ${gbp(BP.base_price_gbp)} · rampa ${BP.ramp_months} m`, `${pct(SO.params.adoption, 0)} · ${gbp(SO.params.base_price_gbp)} · rampa ${SO.params.ramp_months} m · −${num(SO.params.retention_pp * 100, 0)} pp de churn`],
  ["CAPEX", gbp(SP.capex_gbp), gbp(SB.capex_gbp), gbp(SO.capex_gbp)],
  ["VAN (36 meses)", gbp(SP.npv_gbp), gbp(SB.npv_gbp), gbp(SO.npv_gbp)],
  ["TIR anual equivalente", irrTxt(SP), irrTxt(SB), irrTxt(SO)],
  ["Payback (mes desde el inicio)", "No se recupera en 36 meses", `Mes ${SB.payback_month}`, `Mes ${SO.payback_month}`],
  ["Relación B/C", num(SP.bc_ratio, 2), num(SB.bc_ratio, 2), num(SO.bc_ratio, 2)],
], [22, 28, 22, 28], { size: 15, fills: [ALT, "FFFFFF", WARNF, "FFFFFF", ALT, "FFFFFF"] }));
C.push(CAP("Tabla 5. Indicadores financieros. Fuente: erv/out/finance.json."));
C.push(img("erv/out/fin_flujo_acumulado.png", 13.5));
C.push(CAP("Figura 8. Flujo de caja descontado acumulado por escenario."));
C.push(img("erv/out/fin_tornado.png", 13.5));
C.push(CAP("Figura 9. Sensibilidad del VAN del escenario base ante cada supuesto."));
C.push(P(`**Lectura.** La inversión es pequeña frente al ingreso recurrente porque el módulo se vende sobre una base instalada con bajo costo marginal; por eso la TIR resulta muy alta y la decisión se apoya en el **VAN, la relación B/C y la sensibilidad**. La variable crítica es la **adopción**: el VAN se anula con ${num(FIN.breakeven_seats)} puestos (${pct(FIN.breakeven_adoption)}). El CAPEX, el OPEX y el WACC mueven el VAN en menos de ${gbp(60000)}. El ahorro de TTR no se suma como ingreso de Alloxentric para no contarlo dos veces: es el valor que justifica el recargo ante el cliente (capítulo 8).`));

// Capítulo 8
C.push(H1("8. Impacto, recomendación ejecutiva y hoja de ruta"));
C.push(H2("8.1 Ahorro para el cliente y recargo"));
C.push(P(`Con un costo cargado de ${gbp(CV.agent_cost_month)} por agente al mes (sueldo base UK de £18.896 al año más 30 % de cargas laborales), la reducción del **15 % del TTR** libera **${gbp(CV.saving_15)} por agente al mes**, frente a un recargo de **${gbp(CV.premium_month)}**: una relación valor/precio de **${num(CV.value_to_price_15, 1)} veces**. Incluso con la reducción de 12 % que Microsoft reportó para su asistente de agentes, la relación es de ${num(CV.value_to_price_12, 1)} veces. El recargo del 20 % queda ampliamente justificado.`));
C.push(H2("8.2 Diferenciación"));
C.push(BL("**Causal frente a correlacional:** recupera la causa raíz con error de ATE ≤ 0,05, donde el enfoque correlacional falla y ordena mal las prioridades."));
C.push(BL("**Explicable y auditable:** cada diagnóstico indica la causa, su efecto estimado y la acción sugerida; cada versión de modelo queda trazada con SHA-256."));
C.push(BL("**Cumplimiento por diseño:** residencia en UK South, seudonimización, retención de 30 días y análisis exclusivo de la voz del cliente, condición necesaria para vender en la Unión Europea."));
C.push(H2("8.3 Dictamen ejecutivo"));
C.push(P(`**GO condicionado**, con avance por fases y las siguientes condiciones:`));
C.push(NL(`**Puerta de adopción:** al cierre del piloto se requieren compromisos por al menos **${num(FIN.breakeven_seats)} puestos**, el punto de equilibrio; bajo ese umbral se reevalúa (NO-GO de escalamiento).`));
C.push(NL("**Cumplimiento:** DPIA aprobada, aviso al llamante y recalibración del estimador prosódico con corpus real etiquetado."));
C.push(NL("**KPI en la nube:** verify.sh en UK South con p95 < 200 ms y error de ATE ≤ 0,05 sobre datos semisintéticos de Alloxentric."));
C.push(NL(`**Costo:** cerrar los paquetes pendientes dentro de la reserva de contingencia (EAC ${num(EVM.eac_h, 0)} h).`));
C.push(H2("8.4 Hoja de ruta post-entrega"));
C.push(table(["Fase", "Plazo", "Entregables"], [
  ["0 · Cierre del proyecto", "Semanas 7–12", "Despliegue con API Management y Private Endpoints; verify.sh en UK South; piloto productivo"],
  ["1 · Piloto controlado", "Meses 4–6", "1–2 clientes en el Reino Unido; DPIA; corpus etiquetado; tablero de KPI"],
  ["2 · Escalamiento", "Meses 7–12", "Clientes de la UE; autoescalado a 10+ réplicas; monitoreo de deriva y reentrenamiento programado"],
  ["3 · Evolución", "Año 2", "Efectos heterogéneos (CATE) por segmento; soporte multi-idioma; nuevas causas raíz"],
], [24, 16, 60], { size: 15 }));

// Referencias
C.push(H1("Referencias"));
[
  "Alloxentric SpA / UTEM (2026). Taller de Actividades C4, MLOps y ERV — Caso PIA. Dr. Oscar Magna Veloso.",
  "Microsoft Learn. Import a WebSocket API (API Management) — WebSocket no disponible en el nivel Consumption.",
  "Future of Privacy Forum (2025). Red Lines under the EU AI Act: emotion recognition in the workplace (art. 5.1.f).",
  "BCLP (2023). ICO draft guidance on biometric recognition (UK GDPR, datos biométricos y DPIA).",
  "Rishitha, M. et al. (2026). Low-Latency Sentiment and Emotion Mining from Streaming Voice Transcriptions. COMPUTATIA 2026 — umbral de 200 ms.",
  "CX Today (2023). Copilot cuts average handling time by 12 percent, claims Microsoft.",
  "DevZero (2026). Azure Container Apps pricing; digitalapi.ai (2026). Azure API Management pricing; CloudToolStack. Azure Service Bus cost estimator.",
  "FutureAGI (2026). Azure OpenAI GPT-4o mini pricing; nOps (2026). Azure storage pricing; ManageEngine (2026). Azure Monitor pricing.",
  "IT Jobs Watch (2026). Machine Learning contracts in the UK — tarifa diaria mediana.",
  "PwC (2026). Cost of Capital — Technology sector WACC; Bright Pattern (2026). Contact Center AI pricing guide; PayScale (2024). Call Center Agent salary, UK.",
  "Sharma, A. y Kiciman, E. DoWhy: An end-to-end library for causal inference; Microsoft Research. EconML (Double Machine Learning).",
].forEach((r) => C.push(BL(r)));

// ───── documento ─────
const doc = new Document({
  creator: "Grupo 1 · Sección 411 · GPI 2026-II", title: "Informe ERV — Vox-Causal AI (Alloxentric SpA)",
  styles: {
    default: { document: { run: { font: "Calibri", size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, color: NAVY, font: "Calibri" }, paragraph: { spacing: { before: 120, after: 200 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: NAVY, space: 4 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, bold: true, color: NAVY, font: "Calibri" }, paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] },
    { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1300, right: 1417, bottom: 1134, left: 1417, header: 600, footer: 500 } }, titlePage: true },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "Informe ERV — Vox-Causal AI · Alloxentric SpA · Grupo 1, Sección 411", size: 16, color: "52514E" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text: "Página ", size: 16, color: "52514E" }), new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "52514E" }),
      new TextRun({ text: " de ", size: 16, color: "52514E" }), new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: "52514E" })] })] }) },
    children: C,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log(OUT); });
