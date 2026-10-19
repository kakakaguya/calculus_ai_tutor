import json

from ingestion.exercise_layout import ExerciseLayout, layout_from_runs, line_key, load_exercise_layout


RUNS_16_6_PAGE = [
    ("MyriadPro-BoldSemiCn", 9.0, "59."),
    ("TimesLTStd-Roman", 9.0, "(a) Show that the parametric equations"),
    ("TimesLTStd-Italic", 9.0, "x"),
    ("MyriadPro-BoldSemiCn", 9.0, "60–61"),
    ("TimesLTStd-Roman", 9.0, "Find the area of the surface"),
    ("MyriadPro-BoldSemiCn", 9.0, "62."),
    ("TimesLTStd-Italic", 9.0, "z"),
    ("MyriadPro-BoldSemiCn", 14.0, "16.7"),
    ("MyriadPro-Semibold", 13.0, "Surface Integrals"),
    ("TimesLTStd-Roman", 10.0, "The relationship between surface integrals and surface area"),
    ("TimesLTStd-Bold", 10.0, "1."),
    ("TimesLTStd-Roman", 10.0, "short"),
]


def test_layout_records_exercise_numbers_with_text_keys_and_body_text():
    layout = layout_from_runs(RUNS_16_6_PAGE)

    assert layout["items"] == [[59, line_key("(a) Show that the parametric")], [60, line_key("Find the area of the surface")], [62, ""]]
    assert layout["body"] == [line_key("The relationship between surface integrals")]


def test_line_key_keeps_letters_before_the_first_math():
    assert line_key("(a) Show that the $x$ parametric equations") == "ashowthatthe"
    assert line_key("The Relationship between surface integrals") == "therelationshipb"
    assert line_key("$z = 1 + 2x$ that lies inside") == ""
    assert line_key("$$") == ""


def test_exercise_item_lines_match_number_and_leading_text_in_the_same_file():
    layout = ExerciseLayout({"book-179": layout_from_runs(RUNS_16_6_PAGE)})

    assert layout.is_exercise_item("book-179", "59. (a) Show that the parametric equations $x = a$")
    assert layout.is_exercise_item("book-179", "T 60-61 Find the area of the surface correct to four")
    assert layout.is_exercise_item("book-179", "62. $z = 1 + 2x$")
    assert not layout.is_exercise_item("book-179", "59. A different sentence entirely")
    assert not layout.is_exercise_item("book-179", "1. short")
    assert not layout.is_exercise_item("book-180", "59. (a) Show that the parametric equations")
    assert not layout.is_exercise_item("book-179", "The relationship between surface integrals")


def test_body_lines_are_recognised_by_their_leading_text():
    layout = ExerciseLayout({"book-179": layout_from_runs(RUNS_16_6_PAGE)})

    assert layout.is_body_text("book-179", "The relationship between surface integrals and surface area is")
    assert not layout.is_body_text("book-179", "(b) Use the parametric equations")
    assert not layout.is_body_text("book-180", "The relationship between surface integrals")


def test_load_exercise_layout_tolerates_missing_file(tmp_path):
    path = tmp_path / "exercise_layout.json"
    path.write_text(json.dumps({"book-1": {"items": [[3, ""]], "body": []}}), encoding="utf-8")

    assert load_exercise_layout(path).is_exercise_item("book-1", "3. $x^2$")
    assert not load_exercise_layout(tmp_path / "missing.json").is_exercise_item("book-1", "3. $x^2$")


def test_numbered_and_part_lines_are_never_body_text():
    layout = ExerciseLayout({"book-108": {"items": [], "body": [line_key("Find an equation of the ellipse")]}})

    assert layout.is_body_text("book-108", "Find an equation of the ellipse with foci")
    assert not layout.is_body_text("book-108", "17-18 Find an equation of the ellipse. Then find its foci.")
    assert not layout.is_body_text("book-108", "73. Find an equation of the ellipse")
    assert not layout.is_body_text("book-108", "(b) Find an equation of the ellipse")


def test_bare_range_heading_is_an_item_line_not_body_text():
    from ingestion.exercise_layout import MARKDOWN_ITEM

    assert MARKDOWN_ITEM.match("## 13-16")
    assert MARKDOWN_ITEM.match("## 9–48 Test the series for convergence or divergence.")
