"""PDF → Markdown with MinerU's local models (text, inline and display formulas as LaTeX).

MinerU lives in its own virtualenv (.venv-mineru) so its dependencies cannot clash with
Docling's; this script runs from the project venv and calls the mineru-kit CLI.
Parsing is local only: the --remote flag is never passed, so no page leaves this machine.
"""

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import perf_counter

from ingestion.mineru_cleanup import normalize_body

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_DIRECTORY = PROJECT_ROOT / "data" / "pdf_split"
MARKDOWN_DIRECTORY = PROJECT_ROOT / "data" / "markdown"
MINERU_KIT = PROJECT_ROOT / ".venv-mineru" / "bin" / "mineru-kit"
TIER = "standard"  # ONNX layout/OCR models + the MinerU2.5-Pro 1.2B VLM for formulas
OCR_MODE = "ocr"  # force OCR: the PDF text layer maps math symbols wrongly (δ vanishes, > becomes ≥)
TIMEOUT_SECONDS = 1800  # per 5-page PDF; a normal run takes ~3 minutes
OUTPUT_MARKER = "<!-- extractor: mineru -->"


def natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def clean_markdown(markdown: str) -> str:
    return f"{OUTPUT_MARKER}\n\n{normalize_body(markdown)}\n"


def is_current_output(markdown: str) -> bool:
    return markdown.startswith(OUTPUT_MARKER)


def build_command(pdf_path: Path, output_dir: Path) -> list[str]:
    return [str(MINERU_KIT), "parse", str(pdf_path), "--output", str(output_dir),
            "--tier", TIER, "--ocr-mode", OCR_MODE, "--pages", "all"]


def parse_pdf(pdf_path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="mineru-") as raw_dir:
        result = subprocess.run(build_command(pdf_path, Path(raw_dir)), capture_output=True,
                                text=True, timeout=TIMEOUT_SECONDS)
        if result.returncode != 0:
            raise RuntimeError(f"mineru-kit 失敗（exit {result.returncode}）：\n"
                               f"{result.stderr.strip()[-2000:]}")
        outputs = list(Path(raw_dir).rglob("*.md"))
        if len(outputs) != 1:
            raise RuntimeError(f"預期 1 個 Markdown 輸出，實際找到 {len(outputs)} 個")
        return clean_markdown(outputs[0].read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PDF → Markdown（MinerU 本地模型）")
    parser.add_argument("--resume", action="store_true",
                        help="略過已用 MinerU 轉換過的 PDF（中斷後接續用）")
    parser.add_argument("--limit", type=int, help="只處理前 N 份 PDF（測試用）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not MINERU_KIT.exists():
        sys.exit(f"找不到 {MINERU_KIT}，請先依 README 安裝 MinerU")
    pdfs = sorted(PDF_DIRECTORY.glob("*.pdf"), key=lambda p: natural_key(p.name))[:args.limit]
    if not pdfs:
        sys.exit(f"找不到 PDF：{PDF_DIRECTORY}")
    MARKDOWN_DIRECTORY.mkdir(parents=True, exist_ok=True)
    failures = []
    for number, pdf_path in enumerate(pdfs, 1):
        output_path = MARKDOWN_DIRECTORY / f"{pdf_path.stem}.md"
        if (args.resume and output_path.exists()
                and is_current_output(output_path.read_text(encoding="utf-8"))):
            print(f"略過第 {number} 份（已轉換）：{pdf_path.name}", flush=True)
            continue
        print(f"開始處理第 {number}/{len(pdfs)} 份檔案：{pdf_path.name}", flush=True)
        started_at = perf_counter()
        try:
            markdown = parse_pdf(pdf_path)
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            print(f"處理失敗：{pdf_path.name}：{exc}", file=sys.stderr, flush=True)
            failures.append(pdf_path.name)
            continue
        output_path.write_text(markdown, encoding="utf-8")
        print(f"已完成 {output_path.name}（{perf_counter() - started_at:.1f} 秒）", flush=True)
    if failures:
        sys.exit(f"有 {len(failures)} 份 PDF 處理失敗：{', '.join(failures)}")
    print("讀取完成！")


if __name__ == "__main__":
    main()
