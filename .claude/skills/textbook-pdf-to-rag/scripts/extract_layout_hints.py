#!/usr/bin/env python3
"""Extract font-marked text (subsection titles, exercise numbers) from the split PDFs.

    .venv-mineru/bin/python extract_layout_hints.py work/pdf_split \
        --profile work/book_profile.json --out work/layout_hints.json

Each entry of the profile's layout_markers describes one typesetting signature:
    {"name": "subheading", "font": "MyriadPro-Semibold", "size": [10, 12],
     "text": "\\\\w", "after": {"font": "ZapfDingbatsStd", "text": "■"}}
font and text are regexes (font is matched in full), size is an inclusive range in
points, and "after" requires the previous run to match. "with_next": true appends the
following run's text, e.g. an exercise number plus the words of its question, so a
numbered Markdown line can be matched by number and wording. Output, per PDF stem:
    {"Book-12": {"subheading": ["The Chain Rule"], "exercise_item": ["21. Find the ..."]}}
chunk_markdown.py splits section text at "subheading" hints and starts exercises at
lines confirmed by "exercise_item" hints.
"""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_profile import load_profile, natural_key  # noqa: E402
from inspect_fonts import Run, pdf_runs  # noqa: E402


def _run_matches(run: Run, rule: dict) -> bool:
    font, size, text = run
    if "font" in rule and not re.fullmatch(rule["font"], font):
        return False
    if "size" in rule and not rule["size"][0] <= size <= rule["size"][1]:
        return False
    return "text" not in rule or re.search(rule["text"], text) is not None


def marked_text(runs: list[Run], marker: dict) -> list[str]:
    found = []
    for position, run in enumerate(runs):
        if not _run_matches(run, marker):
            continue
        after = marker.get("after")
        if after and (position == 0 or not _run_matches(runs[position - 1], after)):
            continue
        following = runs[position + 1][2] if marker.get("with_next") and position + 1 < len(runs) else ""
        found.append(f"{run[2]} {following}".strip())
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="依字型標記從 PDF 擷取小標題等結構提示")
    parser.add_argument("pdf_dir", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        markers = load_profile(args.profile)["layout_markers"]
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if not markers:
        parser.error("book_profile 沒有 layout_markers；先用 inspect_fonts.py 找出字型標記")
    pdfs = sorted(args.pdf_dir.glob("*.pdf"), key=lambda path: natural_key(path.name))
    hints: dict[str, dict[str, list[str]]] = {}
    totals = {marker["name"]: 0 for marker in markers}
    for pdf in pdfs:
        runs = pdf_runs(pdf)
        hints[pdf.stem] = {marker["name"]: marked_text(runs, marker) for marker in markers}
        for name, texts in hints[pdf.stem].items():
            totals[name] += len(texts)
    args.out.write_text(json.dumps(hints, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(pdfs)} 份 PDF：{totals} → {args.out}")


if __name__ == "__main__":
    main()
