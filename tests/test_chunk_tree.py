import pytest

from ingestion.chunk_tree import example_label, link_chunks, subheading_of


def _row(index: int, kind: str, section: str, text: str, part: str = "body") -> dict:
    return {
        "index": index,
        "id": f"chunk-{index:06d}",
        "kind": kind,
        "part": part,
        "section": section,
        "section_title": f"Title {section}",
        "text": text,
        "source_files": ["book-1.md"],
        "source_spans": [{"file": "book-1.md", "start_line": index, "end_line": index}],
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("## ■ Evaluating Limits at Infinity\n\nBody.", "Evaluating Limits at Infinity"),
        ("■ Infinite Limits at Infinity\n\nBody.", "Infinite Limits at Infinity"),
        ("## Precise Definitions\n\nBody.", "Precise Definitions"),
        ("## 3.4 Limits at Infinity\n\nIntro.", None),
        ("## Section 2.1\n\nIntro.", None),
        ("3.6\n\nIntro.", None),
        ("5.4 Work\n\nIntro.", None),
        ("Plain opening sentence.", None),
    ],
)
def test_subheading_of_reads_the_opening_heading(text, expected):
    assert subheading_of(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("EXAMPLE 3 Find the limit.", "Example 3"),
        ("## EXAMPLE 5A Sketch.", "Example 5A"),
        ("Not an example.", None),
    ],
)
def test_example_label(text, expected):
    assert example_label(text) == expected


def test_examples_hang_under_the_subtopic_before_them():
    rows = [
        _row(1, "section_text", "3.4", "## 3.4 Limits at Infinity\n\nIntro."),
        _row(2, "section_text", "3.4", "## ■ Topic A\n\nConcept A."),
        _row(3, "example", "3.4", "EXAMPLE 1 First."),
        _row(4, "example", "3.4", "EXAMPLE 2 Second."),
        _row(5, "section_text", "3.4", "## Topic B\n\nConcept B."),
        _row(6, "example", "3.4", "EXAMPLE 3 Third."),
        _row(7, "exercises", "3.4", "## Exercises\n\n1. Do it."),
        _row(8, "section_text", "3.5", "## 3.5 Next\n\nIntro."),
        _row(9, "example", "3.5", "EXAMPLE 1 Next first."),
    ]

    nodes = {node.id: node for node in link_chunks(rows)}

    assert nodes["chunk-000003"].parent_id == "chunk-000002"
    assert nodes["chunk-000004"].parent_id == "chunk-000002"
    assert nodes["chunk-000006"].parent_id == "chunk-000005"
    assert nodes["chunk-000009"].parent_id == "chunk-000008"
    assert nodes["chunk-000007"].parent_id is None
    assert nodes["chunk-000002"].parent_id is None
    assert nodes["chunk-000002"].child_ids == ("chunk-000003", "chunk-000004")
    assert nodes["chunk-000008"].child_ids == ("chunk-000009",)
    assert nodes["chunk-000001"].child_ids == ()
    assert nodes["chunk-000003"].subheading == "Topic A"
    assert nodes["chunk-000006"].subheading == "Topic B"
    assert nodes["chunk-000009"].subheading is None
    assert nodes["chunk-000006"].example_label == "Example 3"


def test_example_does_not_attach_to_another_section_or_part():
    rows = [
        _row(1, "section_text", "1.1", "## 1.1 First\n\nIntro."),
        _row(2, "example", "1.2", "EXAMPLE 1 Lost."),
        _row(3, "section_text", "A", "## Numbers\n\nAppendix text.", part="appendix"),
        _row(4, "example", "A", "EXAMPLE 1 Appendix.", part="body"),
    ]

    nodes = {node.id: node for node in link_chunks(rows)}

    assert nodes["chunk-000002"].parent_id is None
    assert nodes["chunk-000004"].parent_id is None
