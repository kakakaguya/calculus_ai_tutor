#!/usr/bin/env python3
"""Show which fonts and sizes a textbook uses, so structure can be read from typesetting.

OCR flattens every heading-like line into '##'. The PDF still knows that a subsection
title is, say, MyriadPro-Semibold after a ZapfDingbats bullet, while an exercise number is
a 9 pt condensed bold. This prints that inventory; book_profile.json layout_markers then
name the combinations worth extracting (see references/03-layout-hints.md).

    python inspect_fonts.py work/pdf_split --limit 10            # font/size inventory
    python inspect_fonts.py work/pdf_split --find "The Chain Rule" # what typesets this text

Needs pypdf (in the MinerU venv: .venv-mineru/bin/python inspect_fonts.py ...).
"""

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_profile import natural_key  # noqa: E402

FONT_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

Run = tuple[str, float, str]


def page_runs(page) -> list[Run]:
    """Consecutive text in one font and rendered size."""
    runs: list[list] = []

    def visit(text, cm, tm, font, size) -> None:
        if not text.strip():
            return
        name = FONT_SUBSET_PREFIX.sub("", str(font.get("/BaseFont", "")).lstrip("/")) if font else ""
        rendered = round(size * abs(tm[0]) * abs(cm[0]), 1)
        if runs and runs[-1][0] == name and runs[-1][1] == rendered:
            runs[-1][2] += text
        else:
            runs.append([name, rendered, text])

    page.extract_text(visitor_text=visit)
    return [(name, size, " ".join(text.split())) for name, size, text in runs]


def pdf_runs(path: Path) -> list[Run]:
    from pypdf import PdfReader

    return [run for page in PdfReader(path).pages for run in page_runs(page)]


def list_pdfs(target: Path, limit: int | None) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(target.glob("*.pdf"), key=lambda path: natural_key(path.name))[:limit]


def inventory(pdfs: list[Path], samples: int) -> None:
    counts: Counter = Counter()
    examples: dict[tuple, list[str]] = defaultdict(list)
    for pdf in pdfs:
        for font, size, text in pdf_runs(pdf):
            counts[(font, size)] += 1
            if len(examples[(font, size)]) < samples and text not in examples[(font, size)]:
                examples[(font, size)].append(text[:60])
    print(f"{len(pdfs)} 份 PDF，{len(counts)} 種字型/字級組合（依出現次數排序）")
    for (font, size), count in counts.most_common():
        print(f"{count:7d}  {font:38s} {size:5.1f}pt  {' | '.join(examples[(font, size)])}")


def find(pdfs: list[Path], needle: str) -> None:
    hits = 0
    for pdf in pdfs:
        runs = pdf_runs(pdf)
        for position, (font, size, text) in enumerate(runs):
            if needle.casefold() in text.casefold():
                previous = runs[position - 1] if position else ("", 0.0, "")
                print(f"{pdf.name}: {font} {size}pt «{text[:70]}»  ← 前一段 {previous[0]} "
                      f"{previous[1]}pt «{previous[2][:20]}»")
                hits += 1
    print(f"共 {hits} 處")


def main() -> None:
    parser = argparse.ArgumentParser(description="列出教科書 PDF 的字型與字級，找出結構標記")
    parser.add_argument("target", type=Path, help="PDF 檔或資料夾")
    parser.add_argument("--limit", type=int, default=10, help="最多讀幾份 PDF")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--find", help="找出這段文字用的字型（以及前一段，可看出項目符號）")
    args = parser.parse_args()
    pdfs = list_pdfs(args.target, args.limit)
    if not pdfs:
        parser.error(f"找不到 PDF：{args.target}")
    if args.find:
        find(pdfs, args.find)
    else:
        inventory(pdfs, args.samples)


if __name__ == "__main__":
    main()
