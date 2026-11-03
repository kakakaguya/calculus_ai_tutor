"""pipeline_status.py tells which stage a work folder is at and what went stale."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from conftest import run_script
from pipeline_status import inspect_work
from run_mineru import LOCK_NAME


def by_key(stages: list[dict]) -> dict[str, dict]:
    return {stage["key"]: stage for stage in stages}


def touch_later(path: Path, seconds: float = 5) -> None:
    later = time.time() + seconds
    os.utime(path, (later, later))


def make_pdfs(work: Path, names: list[str]) -> None:
    (work / "pdf_split").mkdir(exist_ok=True)
    for name in names:
        (work / "pdf_split" / name).write_bytes(b"%PDF-1.4")


def test_empty_folder_starts_at_split(tmp_path):
    status = inspect_work(tmp_path)

    assert status["next"]["key"] == "split"
    assert by_key(status["stages"])["split"]["status"] == "未做"


def test_markdown_only_starts_at_cleanup(work):
    status = inspect_work(work)

    stages = by_key(status["stages"])
    assert stages["split"]["status"] == "不需要"  # no PDFs: the user started from Markdown
    assert stages["ocr"]["status"] == "完成"
    assert stages["clean"]["status"] == "未做"
    assert status["next"]["key"] == "clean"


def test_ocr_progress_counts_missing_parts(work):
    make_pdfs(work, ["Lecture-1.pdf", "Lecture-2.pdf", "Lecture-3.pdf", "Lecture-4.pdf"])

    ocr = by_key(inspect_work(work)["stages"])["ocr"]

    assert ocr["status"] == "部分"
    assert "3 / 4" in ocr["detail"]
    assert any("Lecture-4.pdf" in issue for issue in ocr["issues"])


def test_running_ocr_is_reported_and_not_restarted(work):
    make_pdfs(work, ["Lecture-1.pdf", "Lecture-2.pdf", "Lecture-3.pdf", "Lecture-4.pdf"])
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (work / "markdown" / LOCK_NAME).write_text(f"{sleeper.pid}\n")
        status = inspect_work(work)
    finally:
        sleeper.kill()
        sleeper.wait()

    assert by_key(status["stages"])["ocr"]["status"] == "執行中"
    assert status["next"]["key"] == "ocr"
    assert "不要" in status["next"]["advice"]


def test_cleanup_done_when_backed_up_and_nothing_left_to_change(work):
    result = run_script("clean_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
                        "--backup", work / "backup")
    assert result.returncode == 0, result.stderr

    status = inspect_work(work)

    assert by_key(status["stages"])["clean"]["status"] == "完成"
    assert status["next"]["key"] == "chunk"


def test_profile_rule_added_after_cleanup_makes_it_partial(work):
    run_script("clean_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
               "--backup", work / "backup")
    profile = json.loads((work / "book_profile.json").read_text(encoding="utf-8"))
    profile["cleanup"]["replacements"] = [["Displacement", "Displacement (位移)"]]
    (work / "book_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    clean = by_key(inspect_work(work)["stages"])["clean"]

    assert clean["status"] == "部分"


def test_chunks_go_stale_when_markdown_changes(work):
    run_script("clean_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
               "--backup", work / "backup")
    run_script("chunk_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
               "--out", work / "chunks.jsonl")
    assert by_key(inspect_work(work)["stages"])["chunk"]["status"] == "完成"

    touch_later(work / "markdown" / "Lecture-3.md")

    chunk = by_key(inspect_work(work)["stages"])["chunk"]
    assert chunk["status"] == "過期"
    assert any("Lecture-3.md" in issue for issue in chunk["issues"])


def test_full_pipeline_through_segments(work):
    run_script("clean_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
               "--backup", work / "backup")
    run_script("chunk_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
               "--out", work / "chunks.jsonl")
    run_script("build_segments.py", work / "chunks.jsonl", "--tree", work / "chunk_tree.jsonl",
               "--segments", work / "segments.jsonl")

    status = inspect_work(work)

    stages = by_key(status["stages"])
    assert stages["segments"]["status"] == "完成"
    assert "4 / 4" in stages["segments"]["detail"]
    assert stages["layout"]["status"] == "不需要"  # no PDFs and no layout_markers
    assert status["next"]["key"] == "vectors"


def test_cli_prints_table_and_writes_json(work):
    result = run_script("pipeline_status.py", work, "--json", work / "status.json")

    assert result.returncode == 0, result.stderr
    assert "下一步" in result.stdout
    report = json.loads((work / "status.json").read_text(encoding="utf-8"))
    assert report["stage"] == "status" and report["next"]["key"] == "clean"


def test_missing_early_inputs_are_not_needed_once_later_outputs_exist(work):
    run_script("chunk_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
               "--out", work / "chunks.jsonl")
    run_script("build_segments.py", work / "chunks.jsonl", "--tree", work / "chunk_tree.jsonl",
               "--segments", work / "segments.jsonl")
    for path in (work / "markdown").iterdir():  # intermediate files archived after the run
        path.unlink()

    status = inspect_work(work)

    stages = by_key(status["stages"])
    assert stages["split"]["status"] == stages["ocr"]["status"] == stages["clean"]["status"] == "不需要"
    assert status["next"]["key"] == "vectors"


def test_staleness_from_modification_time_says_so(work):
    run_script("chunk_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
               "--out", work / "chunks.jsonl")
    touch_later(work / "book_profile.json")

    chunk = by_key(inspect_work(work)["stages"])["chunk"]

    assert chunk["status"] == "過期"
    assert "修改時間" in chunk["issues"][0]
