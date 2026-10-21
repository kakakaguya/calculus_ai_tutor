import json

import pytest

from ingestion.build_segments import build_outputs, load_chunks, main


def _row(index: int, kind: str, text: str, section: str = "3.4") -> dict:
    return {
        "index": index,
        "id": f"chunk-{index:06d}",
        "kind": kind,
        "part": "body",
        "section": section,
        "section_title": "Limits at Infinity",
        "text": text,
        "source_files": ["book-1.md"],
        "source_spans": [{"file": "book-1.md", "start_line": 1, "end_line": 2}],
    }


def _write_rows(path, rows) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_load_chunks_reports_the_bad_line(tmp_path):
    path = tmp_path / "chunks.jsonl"
    path.write_text(json.dumps(_row(1, "example", "EXAMPLE 1 A.")) + "\n{broken\n", encoding="utf-8")

    with pytest.raises(ValueError, match="第 2 行"):
        load_chunks(path)


def test_load_chunks_rejects_missing_fields(tmp_path):
    path = tmp_path / "chunks.jsonl"
    path.write_text(json.dumps({"id": "chunk-000001", "kind": "example"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="缺少欄位"):
        load_chunks(path)


def test_segments_carry_headers_and_point_back_to_full_chunks():
    long_example = "EXAMPLE 2 Find the limit.\n\n" + "\n\n".join(["Step text here. " * 5] * 6)
    rows = [
        _row(1, "section_text", "## ■ Evaluating Limits\n\nConcept."),
        _row(2, "example", long_example),
    ]

    nodes, segments = build_outputs(rows, max_tokens=120, min_tokens=10, chars_per_token=1.0,
                                    embed_kinds=frozenset({"section_text", "example"}))

    by_id = {node.id: node for node in nodes}
    example_segments = [segment for segment in segments if segment.chunk_id == "chunk-000002"]
    assert len(example_segments) > 1
    assert by_id["chunk-000002"].segment_ids == tuple(segment.id for segment in example_segments)
    assert example_segments[0].id == "chunk-000002-s01"
    assert all(segment.parent_id == "chunk-000001" for segment in example_segments)
    assert [segment.position for segment in example_segments] == list(
        range(1, len(example_segments) + 1)
    )
    assert all(segment.segment_count == len(example_segments) for segment in example_segments)
    header = example_segments[1].header
    assert header == "3.4 Limits at Infinity | Evaluating Limits | Example 2"
    assert example_segments[1].embed_text.startswith(header + "\n\n")
    assert all(len(segment.embed_text) <= 120 for segment in example_segments)


def test_only_section_text_is_embedded_by_default():
    rows = [
        _row(1, "section_text", "## ■ Topic\n\nConcept."),
        _row(2, "example", "EXAMPLE 1 A."),
        _row(3, "exercises", "## Exercises\n\n1. Do it."),
    ]

    nodes, segments = build_outputs(rows)

    by_id = {node.id: node for node in nodes}
    assert [segment.chunk_id for segment in segments] == ["chunk-000001"]
    assert by_id["chunk-000001"].child_ids == ("chunk-000002",)
    assert by_id["chunk-000002"].segment_ids == ()
    assert by_id["chunk-000003"].segment_ids == ()


def test_header_longer_than_the_budget_is_rejected():
    rows = [_row(1, "section_text", "## ■ Topic\n\nConcept.")]

    with pytest.raises(ValueError, match="標頭"):
        build_outputs(rows, max_tokens=20, min_tokens=10, chars_per_token=1.0)


def test_main_writes_tree_and_segments(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    tree_path = tmp_path / "chunk_tree.jsonl"
    segments_path = tmp_path / "segments.jsonl"
    _write_rows(
        chunks_path,
        [_row(1, "section_text", "## ■ Topic\n\nConcept."), _row(2, "example", "EXAMPLE 1 A.")],
    )

    main(["--input", str(chunks_path), "--tree-output", str(tree_path),
          "--segments-output", str(segments_path)])

    tree = [json.loads(line) for line in tree_path.read_text(encoding="utf-8").splitlines()]
    segments = [json.loads(line) for line in segments_path.read_text(encoding="utf-8").splitlines()]
    assert [node["id"] for node in tree] == ["chunk-000001", "chunk-000002"]
    assert tree[0]["child_ids"] == ["chunk-000002"]
    assert tree[1]["parent_id"] == "chunk-000001"
    assert tree[0]["segment_ids"] == ["chunk-000001-s01"]
    assert tree[1]["segment_ids"] == []
    assert [segment["chunk_id"] for segment in segments] == ["chunk-000001"]
    assert segments[0]["subheading"] == "Topic"


def test_main_can_embed_examples_for_comparison(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    segments_path = tmp_path / "segments.jsonl"
    _write_rows(
        chunks_path,
        [_row(1, "section_text", "## ■ Topic\n\nConcept."), _row(2, "example", "EXAMPLE 1 A.")],
    )

    main(["--input", str(chunks_path), "--tree-output", str(tmp_path / "tree.jsonl"),
          "--segments-output", str(segments_path), "--embed-kinds", "section_text", "example"])

    segments = [json.loads(line) for line in segments_path.read_text(encoding="utf-8").splitlines()]
    assert [segment["chunk_id"] for segment in segments] == ["chunk-000001", "chunk-000002"]


def test_main_refuses_to_overwrite_its_input(tmp_path):
    chunks_path = tmp_path / "chunks.jsonl"
    _write_rows(chunks_path, [_row(1, "example", "EXAMPLE 1 A.")])

    with pytest.raises(SystemExit):
        main(["--input", str(chunks_path), "--tree-output", str(chunks_path)])

    assert json.loads(chunks_path.read_text(encoding="utf-8"))["id"] == "chunk-000001"
