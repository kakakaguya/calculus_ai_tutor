"""Read typesetting hints from the split PDFs that MinerU's Markdown loses.

Writes two files used by chunk_markdown:
- data/subheadings.json: blue ■ subheadings per PDF
- data/exercise_layout.json: exercise numbers and 10 pt body text per PDF

pypdf is installed in .venv-mineru, so run:
    .venv-mineru/bin/python -m ingestion.pdf_layout
"""

import json
from pathlib import Path
import re

from ingestion.exercise_layout import Run, layout_from_runs
from ingestion.ingest_mineru import PDF_DIRECTORY, natural_key
from ingestion.subheadings import DEFAULT_SUBHEADINGS, blue_subheadings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXERCISE_LAYOUT = PROJECT_ROOT / "data" / "exercise_layout.json"
FONT_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


def page_runs(page) -> list[Run]:
    """Consecutive text in the same font and size, with the size as rendered on the page."""
    runs: list[list] = []

    def visit_text(text, cm, tm, font, size) -> None:
        if not text.strip():
            return
        name = FONT_SUBSET_PREFIX.sub("", str(font.get("/BaseFont", "")).lstrip("/")) if font else ""
        rendered = round(size * abs(tm[0]) * abs(cm[0]), 1)
        if runs and runs[-1][0] == name and runs[-1][1] == rendered:
            runs[-1][2] += text
        else:
            runs.append([name, rendered, text])

    page.extract_text(visitor_text=visit_text)
    return [(name, size, " ".join(text.split())) for name, size, text in runs]


def pdf_runs(pdf_path: Path) -> list[Run]:
    from pypdf import PdfReader

    return [run for page in PdfReader(pdf_path).pages for run in page_runs(page)]


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    pdfs = sorted(PDF_DIRECTORY.glob("*.pdf"), key=lambda path: natural_key(path.name))
    if not pdfs:
        raise SystemExit(f"找不到 PDF：{PDF_DIRECTORY}")
    subheadings: dict[str, list[str]] = {}
    exercise_layout: dict[str, dict[str, list]] = {}
    for pdf in pdfs:
        runs = pdf_runs(pdf)
        subheadings[pdf.name] = blue_subheadings([(font, text) for font, _, text in runs])
        exercise_layout[pdf.stem] = layout_from_runs(runs)
    _write_json(DEFAULT_SUBHEADINGS, subheadings)
    _write_json(DEFAULT_EXERCISE_LAYOUT, exercise_layout)
    heading_count = sum(len(headings) for headings in subheadings.values())
    item_count = sum(len(layout["items"]) for layout in exercise_layout.values())
    print(f"已讀取 {len(pdfs)} 份 PDF：{heading_count} 個藍色小標題、{item_count} 個習題題號")


if __name__ == "__main__":
    main()
