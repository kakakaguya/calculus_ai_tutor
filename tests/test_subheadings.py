import json

from ingestion.subheadings import SubheadingIndex, blue_subheadings, heading_key, load_subheadings


def test_blue_subheadings_follow_standard_bullet_runs():
    runs = [
        ("ZapfDingbatsITC", "■"),
        ("ZapfDingbatsStd", "■"),
        ("MyriadPro-Semibold", " The Law of Sines and the Law of Cosines "),
        ("MyriadPro-Bold", "Law of Sines"),
        ("MyriadPro-Semibold", "A30"),
        ("ZapfDingbatsStd", "■"),
        ("MyriadPro-Bold", "Not a subheading font"),
    ]

    assert blue_subheadings(runs) == ["The Law of Sines and the Law of Cosines"]


def test_heading_key_ignores_math_bullets_quotes_and_spacing():
    assert heading_key("## ■ Type 1: Infinite Intervals") == heading_key("Type 1:Infinite Intervals")
    assert heading_key("Rolle's Theorem") == heading_key("Rolle’s Theorem")
    assert heading_key("## The Number $e$ as a Limit") == "thenumberasalimit"


def test_index_matches_heading_lines_only():
    index = SubheadingIndex(["Properties of the Cross Product", "Infinite Limits at Infinity"])

    assert index.matches("## ■ Properties of the Cross Product")
    assert index.matches("## Properties of the Cross Product")
    assert index.matches("■ Infinite Limits at Infinity")
    assert not index.matches("Properties of the Cross Product")
    assert not index.matches("## Limits and Technology")
    assert not SubheadingIndex([]).matches("## Anything")


def test_index_accepts_prefix_only_when_pdf_text_stopped_at_math():
    index = SubheadingIndex(["The Number", "Applications", "Area Between Curves: Integrating With Respect to"])

    assert index.matches("## The Number $e$ as a Limit")
    assert index.matches("## ■ Area Between Curves: Integrating With Respect to y")
    assert not index.matches("## Applications of Differentiation")


def test_load_subheadings_reads_json_and_tolerates_missing_file(tmp_path):
    path = tmp_path / "subheadings.json"
    path.write_text(json.dumps({"book-1.pdf": ["Properties of the Cross Product"]}), encoding="utf-8")

    assert load_subheadings(path).matches("## Properties of the Cross Product")
    assert not load_subheadings(tmp_path / "missing.json").matches("## Properties of the Cross Product")
