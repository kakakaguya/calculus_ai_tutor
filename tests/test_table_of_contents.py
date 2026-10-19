from ingestion.table_of_contents import (
    TableOfContents,
    is_toc_file,
    parse_appendix_lines,
    parse_toc_lines,
)


def test_parses_list_plain_heading_and_code_block_entries():
    lines = [
        "## Contents",
        "- 1.1 Four Ways to Represent a Function 8",
        "1.2 Mathematical Models: A Catalog of Essential Functions 21",
        "## 7.8 Improper Integrals 580",
        "3.9 Antiderivatives 285 Review 292",
        "5.2 Volumes 374   ",
    ]

    entries = parse_toc_lines(lines)

    assert [(entry.section, entry.title, entry.page) for entry in entries] == [
        ("1.1", "Four Ways to Represent a Function", 8),
        ("1.2", "Mathematical Models: A Catalog of Essential Functions", 21),
        ("3.9", "Antiderivatives", 285),
        ("5.2", "Volumes", 374),
        ("7.8", "Improper Integrals", 580),
    ]


def test_parses_table_row_with_escaped_star_and_orders_by_page():
    lines = [
        "| 6.2 | Exponential Functions and Their Derivatives 420 | 6.2\\* | The Natural Logarithmic Function 451 |",
        "| 6.4 | Derivatives of Logarithmic Functions 440 | 6.4* | General Logarithmic and Exponential Functions 468 |",
    ]

    entries = parse_toc_lines(lines)

    assert [entry.section for entry in entries] == ["6.2", "6.4", "6.2*", "6.4*"]
    assert entries[2].title == "The Natural Logarithmic Function"


def test_first_occurrence_of_a_section_wins():
    entries = parse_toc_lines(["1.1 First Title 8", "1.1 Repeated Title 99"])

    assert [(entry.section, entry.title) for entry in entries] == [("1.1", "First Title")]


def test_detects_contents_heading_or_many_entries():
    assert is_toc_file(["<!-- extractor: mineru -->", "## Contents", "- Preface x"])
    assert is_toc_file([f"13.{n} Some Title {900 + n}" for n in range(1, 11)])
    assert not is_toc_file(["## 1.1", "## Four Ways to Represent a Function", "Text 12"])


def test_order_and_upcoming_title_lookup():
    toc = TableOfContents(
        parse_toc_lines(
            [
                "1.4 The Tangent and Velocity Problems 45",
                "1.5 The Limit of a Function 51",
                "1.6 Calculating Limits Using the Limit Laws 62",
                "6.4 Derivatives of Logarithmic Functions 440",
                "6.2* The Natural Logarithmic Function 451",
            ]
        )
    )

    assert toc.title_for("1.5") == "The Limit of a Function"
    assert toc.title_for("9.9") is None
    assert toc.upcoming_section_titled("## The Limit of a Function", "1.4") == "1.5"
    assert toc.upcoming_section_titled("  the  LIMIT of a function ", "1.4") == "1.5"
    assert toc.upcoming_section_titled("The Tangent and Velocity Problems", None) == "1.4"
    assert toc.upcoming_section_titled("## Calculating Limits Using the Limit Laws", "1.5") == "1.6"
    assert toc.upcoming_section_titled("## Calculating Limits Using the Limit Laws", "1.4") == "1.6"
    assert toc.upcoming_section_titled(
        "## Calculating Limits Using the Limit Laws", "1.4", numbered_sections=frozenset({"1.5"})
    ) is None
    assert toc.upcoming_section_titled(
        "## Calculating Limits Using the Limit Laws", "1.5", numbered_sections=frozenset({"1.6"})
    ) == "1.6"
    assert toc.upcoming_section_titled("## Derivatives of Logarithmic Functions", "1.4") is None
    assert toc.upcoming_section_titled("## Continuity", "1.4") is None
    assert toc.upcoming_section_titled("## The Limit of a Function", "1.6") is None
    assert toc.is_before("6.4", "6.2*")
    assert not toc.is_before("6.2*", "6.4")
    assert toc.is_before("1.6", "16.9")
    assert not toc.is_before("1.5", "1.5")


def test_empty_table_falls_back_to_numeric_order():
    toc = TableOfContents(())

    assert toc.is_before("1.8", "16.9")
    assert toc.upcoming_section_titled("## Anything", "1.1") is None


def test_parses_appendix_entries_with_lettered_pages():
    lines = [
        "## Appendixes",
        "A1",
        "A Numbers, Inequalities, and Absolute Values A2",
        "B Coordinate Geometry and Lines A10",
        "F Proofs of Theorems A41",
        "## Index A135",
        "- 16.10 Summary 1246",
    ]

    entries = parse_appendix_lines(lines)

    assert [(entry.section, entry.title, entry.page) for entry in entries] == [
        ("A", "Numbers, Inequalities, and Absolute Values", 2),
        ("B", "Coordinate Geometry and Lines", 10),
        ("F", "Proofs of Theorems", 41),
    ]


def test_upcoming_appendix_lookup_follows_letter_order():
    toc = TableOfContents(
        (),
        parse_appendix_lines(["A Numbers A2", "B Coordinate Geometry A10", "C Graphs A16"]),
    )

    assert toc.has_appendixes
    assert toc.upcoming_appendix_titled("## Numbers", None) == "A"
    assert toc.upcoming_appendix_titled("## Coordinate Geometry", "A") == "B"
    assert toc.upcoming_appendix_titled("## Graphs", "A") == "C"
    assert toc.upcoming_appendix_titled("## Graphs", None) == "C"
    assert toc.upcoming_appendix_titled("## Numbers", "B") is None
    assert toc.title_for("B") == "Coordinate Geometry"
    assert not TableOfContents(()).has_appendixes
