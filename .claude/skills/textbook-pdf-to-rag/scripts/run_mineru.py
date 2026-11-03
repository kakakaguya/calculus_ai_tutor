#!/usr/bin/env python3
"""Convert split PDFs to Markdown with MinerU's local models, one PDF at a time.

    python run_mineru.py --input work/pdf_split --output work/markdown \
        --mineru-kit .venv-mineru/bin/mineru-kit [--limit 2] [--redo name.pdf]

Existing outputs are never overwritten: a rerun continues where an interrupted run
stopped, and Markdown someone fixed by hand survives. Use --redo NAME for the one file
you really want converted again. --remote is never passed, so no page leaves the machine.
Each output starts with a marker line so later steps know it came from MinerU.
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter

OUTPUT_MARKER = "<!-- extractor: mineru -->"
# A text layer often maps math glyphs wrongly (δ vanishes, > becomes ≥), so force OCR.
DEFAULT_OCR_MODE = "ocr"
DEFAULT_TIER = "standard"
DEFAULT_TIMEOUT = 1800  # seconds per PDF; a 5-page part normally takes about 3 minutes


def natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", name)]


def find_mineru_kit(explicit: Path | None) -> Path:
    candidates = [explicit] if explicit else [Path(".venv-mineru/bin/mineru-kit")]
    on_path = shutil.which("mineru-kit")
    if not explicit and on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError("找不到 mineru-kit；請先依 references/01-ocr-mineru.md 安裝，"
                            "或用 --mineru-kit 指定路徑")


def convert(kit: Path, pdf: Path, tier: str, ocr_mode: str, timeout: int) -> str:
    with tempfile.TemporaryDirectory(prefix="mineru-") as raw_dir:
        command = [str(kit), "parse", str(pdf), "--output", raw_dir, "--tier", tier,
                   "--ocr-mode", ocr_mode, "--pages", "all"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"mineru-kit exit {result.returncode}：{result.stderr.strip()[-1500:]}")
        outputs = list(Path(raw_dir).rglob("*.md"))
        if len(outputs) != 1:
            raise RuntimeError(f"預期 1 個 Markdown 輸出，實際 {len(outputs)} 個")
        return f"{OUTPUT_MARKER}\n\n{outputs[0].read_text(encoding='utf-8').strip()}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="用 MinerU 本機模型把 PDF 轉成 Markdown")
    parser.add_argument("--input", type=Path, required=True, help="切好的 PDF 資料夾")
    parser.add_argument("--output", type=Path, required=True, help="Markdown 輸出資料夾")
    parser.add_argument("--mineru-kit", type=Path)
    parser.add_argument("--tier", default=DEFAULT_TIER)
    parser.add_argument("--ocr-mode", default=DEFAULT_OCR_MODE)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--limit", type=int, help="只處理前 N 份（先小量試跑）")
    parser.add_argument("--redo", action="append", default=[], help="強制重轉這份 PDF（可重複）")
    args = parser.parse_args()

    try:
        kit = find_mineru_kit(args.mineru_kit)
    except FileNotFoundError as error:
        sys.exit(str(error))
    pdfs = sorted(args.input.glob("*.pdf"), key=lambda path: natural_key(path.name))[:args.limit]
    if not pdfs:
        sys.exit(f"找不到 PDF：{args.input}")
    unknown = set(args.redo) - {pdf.name for pdf in pdfs}
    if unknown:
        sys.exit(f"--redo 指定的檔案不在輸入中：{', '.join(sorted(unknown))}")
    args.output.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    for number, pdf in enumerate(pdfs, 1):
        target = args.output / f"{pdf.stem}.md"
        if target.exists() and pdf.name not in args.redo:
            print(f"[{number}/{len(pdfs)}] 略過（已存在）：{target.name}", flush=True)
            continue
        print(f"[{number}/{len(pdfs)}] 轉換 {pdf.name}", flush=True)
        started = perf_counter()
        try:
            markdown = convert(kit, pdf, args.tier, args.ocr_mode, args.timeout)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            print(f"  失敗：{error}", file=sys.stderr, flush=True)
            failures.append(pdf.name)
            continue
        target.write_text(markdown, encoding="utf-8")
        print(f"  完成（{perf_counter() - started:.0f} 秒）", flush=True)
    if failures:
        sys.exit(f"{len(failures)} 份失敗：{', '.join(failures)}；可用 --redo 單獨重試")
    print("全部完成")


if __name__ == "__main__":
    main()
