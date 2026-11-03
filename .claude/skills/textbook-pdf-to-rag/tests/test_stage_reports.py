"""Every stage script can write a machine-readable summary with --json."""

import json
import os
from pathlib import Path

import pytest

from conftest import run_script
from stage_report import write_report


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_write_report_adds_stage_and_time_and_skips_when_no_path(tmp_path):
    write_report(None, "split", ok=True)  # no path: nothing written, no error
    target = tmp_path / "reports" / "split.json"

    write_report(target, "split", ok=True, parts=3)

    report = read(target)
    assert (report["stage"], report["ok"], report["parts"]) == ("split", True, 3)
    assert report["finished_at"]
    assert not list(target.parent.glob("*.tmp"))


def test_clean_dry_run_reports_rule_counts_without_writing(work):
    before = (work / "markdown" / "Lecture-2.md").read_text(encoding="utf-8")

    result = run_script("clean_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
                        "--dry-run", "--json", work / "clean.json")

    assert result.returncode == 0, result.stderr
    report = read(work / "clean.json")
    assert report["stage"] == "clean" and report["dry_run"] is True
    assert "Lecture-2.md" in report["files_changed"]
    assert any(name.startswith("刪行") for name in report["rule_totals"])
    assert (work / "markdown" / "Lecture-2.md").read_text(encoding="utf-8") == before


def test_clean_reports_protected_files_it_left_alone(work):
    profile = json.loads((work / "book_profile.json").read_text(encoding="utf-8"))
    profile["protected_files"] = ["Lecture-2.md"]
    (work / "book_profile.json").write_text(json.dumps(profile), encoding="utf-8")

    run_script("clean_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
               "--dry-run", "--json", work / "clean.json")

    report = read(work / "clean.json")
    assert "Lecture-2.md" in report["protected_would_change"]
    assert "Lecture-2.md" not in report["files_changed"]


def test_chunk_segments_and_validate_reports(work):
    chunks, tree, segments = work / "chunks.jsonl", work / "chunk_tree.jsonl", work / "segments.jsonl"

    chunked = run_script("chunk_markdown.py", work / "markdown", "--profile", work / "book_profile.json",
                         "--out", chunks, "--json", work / "chunks.json")
    built = run_script("build_segments.py", chunks, "--tree", tree, "--segments", segments,
                       "--json", work / "segments.json")
    validated = run_script("validate_chunks.py", chunks, "--json", work / "validate.json")

    assert chunked.returncode == 0, chunked.stderr
    assert built.returncode == 0, built.stderr
    chunk_report = read(work / "chunks.json")
    assert chunk_report["stage"] == "chunk"
    assert chunk_report["records"] == sum(chunk_report["kinds"].values()) > 0
    assert chunk_report["kinds"]["example"] == 4  # EXAMPLE 1-2 in Lecture-2, two more in Lecture-3
    segment_report = read(work / "segments.json")
    assert segment_report["stage"] == "segments"
    assert segment_report["linked_examples"] == segment_report["examples"] == 4
    assert segment_report["over_embed_limit"] == 0
    validate_report = read(work / "validate.json")
    assert validate_report["stage"] == "validate"
    assert validate_report["chunks"] == chunk_report["records"]
    assert validate_report["fail"] == 0 and validated.returncode == 0


def test_split_dry_run_report_lists_the_plan(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    for _ in range(12):
        writer.add_blank_page(width=200, height=200)
    pdf = tmp_path / "book.pdf"
    with open(pdf, "wb") as handle:
        writer.write(handle)

    result = run_script("split_pdf.py", pdf, "--out", tmp_path / "pdf_split", "--pages-per-part", "5",
                        "--exclude", "6-7", "--dry-run", "--json", tmp_path / "split.json")

    assert result.returncode == 0, result.stderr
    report = read(tmp_path / "split.json")
    assert report["dry_run"] is True and report["excluded_pages"] == [6, 7]
    assert [part["pages"] for part in report["parts"]] == [[1, 5], [8, 12]]
    assert not (tmp_path / "pdf_split").exists()


def test_ocr_report_lists_failures(tmp_path):
    pdfs, out = tmp_path / "pdf_split", tmp_path / "markdown"
    pdfs.mkdir()
    (pdfs / "Book-1.pdf").write_bytes(b"%PDF-1.4")
    kit = tmp_path / "mineru-kit"
    kit.write_text("#!/bin/sh\necho broken model >&2\nexit 3\n")
    os.chmod(kit, 0o755)

    result = run_script("run_mineru.py", "--input", pdfs, "--output", out, "--mineru-kit", kit,
                        "--json", tmp_path / "ocr.json")

    assert result.returncode != 0
    report = read(tmp_path / "ocr.json")
    assert report["stage"] == "ocr" and report["ok"] is False
    assert [failure["file"] for failure in report["failed"]] == ["Book-1.pdf"]
    assert "broken model" in report["failed"][0]["error"]
