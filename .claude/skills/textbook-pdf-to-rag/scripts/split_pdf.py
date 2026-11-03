#!/usr/bin/env python3
"""Split a textbook PDF into small contiguous parts for OCR and record the page map.

    python split_pdf.py book.pdf --out work/pdf_split --pages-per-part 5 --exclude 1-12,401-420

Writes <stem>-<n>.pdf plus split_manifest.json (part file -> original 1-based pages), so
chunks can later be traced back to book pages. Excluded pages (front matter, exercise
pages, answer keys) never reach OCR. A part never spans an excluded gap, which keeps
every part a contiguous page range. Needs pypdf.
"""

import argparse
import glob
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_report import write_report  # noqa: E402


def parse_ranges(spec: str, page_count: int) -> set[int]:
    """'1-3,7' -> {1, 2, 3, 7}; pages are 1-based and must exist in the PDF."""
    pages: set[int] = set()
    for part in filter(None, (piece.strip() for piece in spec.split(","))):
        start_text, _, end_text = part.partition("-")
        try:
            start, end = int(start_text), int(end_text or start_text)
        except ValueError as error:
            raise ValueError(f"無法解讀頁碼範圍：{part!r}") from error
        if not 1 <= start <= end <= page_count:
            raise ValueError(f"頁碼範圍 {part} 超出 1-{page_count}")
        pages.update(range(start, end + 1))
    return pages


def plan_parts(page_count: int, excluded: set[int], pages_per_part: int) -> list[list[int]]:
    """Contiguous runs of kept pages, each cut into parts of at most pages_per_part."""
    parts: list[list[int]] = []
    current: list[int] = []
    for page in range(1, page_count + 1):
        if page in excluded:
            if current:
                parts.append(current)
            current = []
            continue
        current.append(page)
        if len(current) == pages_per_part:
            parts.append(current)
            current = []
    if current:
        parts.append(current)
    return parts


def main() -> None:
    parser = argparse.ArgumentParser(description="把教科書 PDF 切成小份給 OCR，並記錄頁碼對照")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="輸出資料夾")
    parser.add_argument("--pages-per-part", type=int, default=5)
    parser.add_argument("--exclude", default="", help="要排除的頁碼，例如 1-12,401-420")
    parser.add_argument("--dry-run", action="store_true", help="只印出切分計畫")
    parser.add_argument("--force", action="store_true", help="輸出資料夾已有切好的檔案時仍寫入")
    parser.add_argument("--json", type=Path, help="同時把切分計畫／結果寫成 JSON")
    args = parser.parse_args()

    from pypdf import PdfReader, PdfWriter

    if args.pages_per_part <= 0:
        parser.error("--pages-per-part 必須大於 0")
    reader = PdfReader(args.pdf)
    page_count = len(reader.pages)
    try:
        excluded = parse_ranges(args.exclude, page_count)
    except ValueError as error:
        parser.error(str(error))
    parts = plan_parts(page_count, excluded, args.pages_per_part)
    stem = args.pdf.stem
    plan = [{"file": f"{stem}-{number}.pdf", "pages": [pages[0], pages[-1]]}
            for number, pages in enumerate(parts, 1)]

    def report(dry_run: bool) -> None:
        write_report(args.json, "split", ok=True, dry_run=dry_run, source=args.pdf.name,
                     source_pages=page_count, excluded_pages=sorted(excluded), parts=plan)

    print(f"{args.pdf.name}：共 {page_count} 頁，排除 {len(excluded)} 頁，切成 {len(parts)} 份")
    if args.dry_run:
        for part in plan:
            print(f"  {part['file']}  第 {part['pages'][0]}-{part['pages'][1]} 頁")
        report(dry_run=True)
        return

    # glob.escape: textbook file names often contain [ ] (e.g. "Calculus[1]"), which glob reads as a pattern
    existing = list(args.out.glob(f"{glob.escape(stem)}-*.pdf")) if args.out.exists() else []
    if existing and not args.force:
        sys.exit(f"{args.out} 已有 {len(existing)} 份切好的 PDF；它們可能已經 OCR 過。"
                 "確認要覆蓋再加 --force")
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_parts = []
    for number, pages in enumerate(parts, 1):
        writer = PdfWriter()
        for page in pages:
            writer.add_page(reader.pages[page - 1])
        name = f"{stem}-{number}.pdf"
        with open(args.out / name, "wb") as handle:
            writer.write(handle)
        manifest_parts.append({"file": name, "pages": pages})
    manifest = {
        "source": args.pdf.name,
        "source_pages": page_count,
        "pages_per_part": args.pages_per_part,
        "excluded_pages": sorted(excluded),
        "parts": manifest_parts,
    }
    (args.out / "split_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"已寫入 {len(parts)} 份 PDF 與 split_manifest.json 至 {args.out}")
    report(dry_run=False)


if __name__ == "__main__":
    main()
