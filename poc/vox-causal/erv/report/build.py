"""Construye el Informe ERV en dos pasadas (la segunda escribe los números de página del índice).

Uso:  python erv/report/build.py
Requiere: Node.js con 'docx', LibreOffice (soffice) y poppler (pdftotext).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOCX = HERE / "Informe_ERV_VoxCausal_Grupo1.docx"
PDF = HERE / "Informe_ERV_VoxCausal_Grupo1.pdf"
PAGES = HERE / "pages.json"
CHAPTERS = [
    "Resumen ejecutivo", "1. Contexto y problema", "2. Gestión y control del proyecto (EVM)", "3. Arquitectura C4",
    "4. Pipeline MLOps, inferencia y resolución del incidente", "5. Evidencia del repositorio y gobernanza",
    "6. Métricas objetivas de software e IA", "7. Evaluación financiera ERV",
    "8. Impacto, recomendación ejecutiva y hoja de ruta", "Referencias",
]


def soffice() -> str:
    return shutil.which("soffice") or shutil.which("libreoffice") or "soffice"


def build(pages_file: Path | None) -> None:
    args = ["node", str(HERE / "build_report.js")] + ([str(pages_file)] if pages_file else [])
    subprocess.run(args, check=True, cwd=ROOT)
    subprocess.run([soffice(), "--headless", "--convert-to", "pdf", "--outdir", str(HERE), str(DOCX)],
                   check=True, cwd=HERE, capture_output=True)


def find_pages() -> dict[str, int]:
    text = subprocess.run(["pdftotext", "-layout", str(PDF), "-"], check=True, capture_output=True, text=True).stdout
    pages = text.split("\f")
    found: dict[str, int] = {}
    for title in CHAPTERS:
        pat = re.compile(r"^\s*" + re.escape(title) + r"\s*$", re.M)
        for i, page in enumerate(pages[2:], start=3):  # saltar portada e índice
            if pat.search(page):
                found[title] = i
                break
    return found


def main() -> int:
    build(None)
    pages = find_pages()
    PAGES.write_text(json.dumps(pages, ensure_ascii=False, indent=2))
    build(PAGES)
    if find_pages() != pages:
        print("Advertencia: la paginación cambió entre pasadas", file=sys.stderr)
    total = len(subprocess.run(["pdftotext", str(PDF), "-"], capture_output=True, text=True).stdout.split("\f")) - 1
    print(json.dumps(pages, ensure_ascii=False), f"· {total} páginas")
    missing = [c for c in CHAPTERS if c not in pages]
    if missing:
        print("No se encontraron:", missing, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
