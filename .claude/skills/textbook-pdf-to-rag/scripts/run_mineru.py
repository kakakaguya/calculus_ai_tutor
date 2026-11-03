#!/usr/bin/env python3
"""Convert split PDFs to Markdown with MinerU's local models, one PDF at a time.

    python run_mineru.py --input work/pdf_split --output work/markdown \
        --mineru-kit .venv-mineru/bin/mineru-kit [--limit 2] [--redo name.pdf]

Existing outputs are never overwritten: a rerun continues where an interrupted run
stopped, and Markdown someone fixed by hand survives. Use --redo NAME for the one file
you really want converted again. --remote is never passed, so no page leaves the machine.
Each output starts with a marker line so later steps know it came from MinerU.

A whole book takes hours, longer than a tool call may wait, so it is usually started in
the background. A lock file in the output folder holds the running PID: a second run on
the same folder refuses to start (two runs would share one GPU and race on the same
files), and a lock left by a killed run is taken over. Outputs are written to a temp
file and renamed, so an interrupted run never leaves half a Markdown file that the next
run would skip as already done.
"""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_report import write_report  # noqa: E402

OUTPUT_MARKER = "<!-- extractor: mineru -->"
LOCK_NAME = ".run_mineru.lock"
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


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # exists, owned by someone else
        return True
    return True


def lock_owner(folder: Path) -> int | None:
    """PID of a live run holding folder's lock, or None."""
    try:
        pid = int((folder / LOCK_NAME).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if pid_alive(pid) else None


def acquire_lock(folder: Path) -> Path:
    lock = folder / LOCK_NAME
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = lock_owner(folder)
            if owner is not None:
                raise RuntimeError(
                    f"另一個 run_mineru.py（PID {owner}）正在寫入 {folder}，不要同時跑兩個"
                    "（會搶同一張 GPU、互相覆蓋）。用 pipeline_status.py 看進度，等它結束再接著跑")
            lock.unlink(missing_ok=True)  # left by a run that was killed
            continue
        with os.fdopen(descriptor, "w") as handle:
            handle.write(f"{os.getpid()}\n")
        return lock
    raise RuntimeError(f"無法取得 {lock}；請確認沒有其他 run_mineru.py 在執行")


def write_atomic(target: Path, text: str) -> None:
    partial = target.with_name(target.name + ".part")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, target)


def convert_all(pdfs: list[Path], args: argparse.Namespace, kit: Path) -> dict:
    converted: list[str] = []
    failed: list[dict] = []
    skipped = 0
    started_all = perf_counter()
    for number, pdf in enumerate(pdfs, 1):
        target = args.output / f"{pdf.stem}.md"
        if target.exists() and pdf.name not in args.redo:
            print(f"[{number}/{len(pdfs)}] 略過（已存在）：{target.name}", flush=True)
            skipped += 1
            continue
        print(f"[{number}/{len(pdfs)}] 轉換 {pdf.name}", flush=True)
        started = perf_counter()
        try:
            markdown = convert(kit, pdf, args.tier, args.ocr_mode, args.timeout)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            print(f"  失敗：{error}", file=sys.stderr, flush=True)
            failed.append({"file": pdf.name, "error": str(error)})
            continue
        write_atomic(target, markdown)
        converted.append(pdf.name)
        print(f"  完成（{perf_counter() - started:.0f} 秒）", flush=True)
    return {"ok": not failed, "total": len(pdfs), "converted": converted,
            "skipped_existing": skipped, "failed": failed,
            "seconds": round(perf_counter() - started_all)}


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
    parser.add_argument("--json", type=Path, help="同時把轉換結果（含失敗清單）寫成 JSON")
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
    try:
        lock = acquire_lock(args.output)
    except RuntimeError as error:
        sys.exit(str(error))
    try:
        result = convert_all(pdfs, args, kit)
    finally:
        lock.unlink(missing_ok=True)
    write_report(args.json, "ocr", **result)
    if result["failed"]:
        names = ", ".join(failure["file"] for failure in result["failed"])
        sys.exit(f"{len(result['failed'])} 份失敗：{names}；可用 --redo 單獨重試")
    print("全部完成")


if __name__ == "__main__":
    main()
