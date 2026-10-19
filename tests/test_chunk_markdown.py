import json
import os

import pytest

import ingestion.chunk_markdown as chunker
from ingestion.chunk_markdown import chunk_markdown_files, main, write_chunks_jsonl


def test_chunks_section_text_and_examples_in_natural_file_order(tmp_path):
    later_file = tmp_path / "unit-10.md"
    earlier_file = tmp_path / "unit-2.md"
    earlier_file.write_text(
        "## 1.1\n## Four Ways to Represent a Function\nDefinition text.\n\n"
        "EXAMPLE 1 Find the function value.\n## SOLUTION\nAnswer one.\n",
        encoding="utf-8",
    )
    later_file.write_text(
        "EXAMPLE 2 Find the domain.\n## SOLUTION\nAnswer two.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([later_file, earlier_file])

    assert [chunk.index for chunk in chunks] == [1, 2, 3]
    assert [chunk.kind for chunk in chunks] == ["section_text", "example", "example"]
    assert chunks[0].section == "1.1"
    assert chunks[0].section_title == "Four Ways to Represent a Function"
    assert "Definition text." in chunks[0].text
    assert "EXAMPLE 1" in chunks[1].text
    assert "## SOLUTION" in chunks[1].text
    assert "Answer one." in chunks[1].text
    assert "EXAMPLE 2" in chunks[2].text
    assert "Answer two." in chunks[2].text
    assert chunks[1].source_files == ("unit-2.md",)
    assert chunks[2].source_files == ("unit-10.md",)
    assert chunks[0].chunk_id == chunk_markdown_files([earlier_file, later_file])[0].chunk_id


def test_example_and_solution_continue_across_files(tmp_path):
    first_file = tmp_path / "part-1.md"
    second_file = tmp_path / "part-2.md"
    first_file.write_text("## 1.2\nEXAMPLE 3 Solve the equation.\nQuestion details.\n", encoding="utf-8")
    second_file.write_text("## SOLUTION\nWorked answer.\n## 1.3\nNext section text.\n", encoding="utf-8")

    chunks = chunk_markdown_files([first_file, second_file])

    example = next(chunk for chunk in chunks if chunk.kind == "example")
    next_section = next(chunk for chunk in chunks if chunk.section == "1.3")
    assert example.section == "1.2"
    assert "Question details." in example.text
    assert "Worked answer." in example.text
    assert example.source_files == ("part-1.md", "part-2.md")
    assert example.source_spans == (
        {"file": "part-1.md", "start_line": 2, "end_line": 3},
        {"file": "part-2.md", "start_line": 1, "end_line": 2},
    )
    assert "Next section text." in next_section.text


def test_duplicate_basenames_keep_distinct_source_paths(tmp_path):
    first_file = tmp_path / "first" / "same.md"
    second_file = tmp_path / "second" / "same.md"
    first_file.parent.mkdir()
    second_file.parent.mkdir()
    first_file.write_text("## 1.1\nFirst section.\n", encoding="utf-8")
    second_file.write_text("## 1.2\nSecond section.\n", encoding="utf-8")

    chunks = chunk_markdown_files([first_file, second_file])

    assert chunks[0].source_files == ("first/same.md",)
    assert chunks[1].source_files == ("second/same.md",)


def test_numbered_section_titles_close_examples(tmp_path):
    markdown_file = tmp_path / "sections.md"
    markdown_file.write_text(
        "## 1.1\n## First Section\nDefinition.\n"
        "EXAMPLE 1 Solve it.\n## SOLUTION\nAnswer.\n"
        "## 1.2 Second Section\nSecond section text.\n"
        "## Section 1.3 Third Section\nThird section text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert [chunk.section for chunk in chunks] == ["1.1", "1.1", "1.2", "1.3"]
    assert chunks[1].kind == "example"
    assert "Second section text." not in chunks[1].text
    assert chunks[2].section_title == "Second Section"
    assert chunks[3].section_title == "Third Section"


@pytest.mark.parametrize("indent", range(4))
def test_indented_numbered_section_heading_closes_example(tmp_path, indent):
    markdown_file = tmp_path / "indented-section.md"
    markdown_file.write_text(
        "## 1.1\nEXAMPLE 1 Solve it.\n## SOLUTION\nAnswer.\n"
        f"{' ' * indent}## 1.2 Next Section\nNext section text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert [chunk.section for chunk in chunks] == ["1.1", "1.1", "1.2"]
    assert chunks[1].kind == "example"
    assert "Next section text." not in chunks[1].text
    assert chunks[2].section_title == "Next Section"


def test_plain_section_number_then_exercises_splits_after_solution(tmp_path):
    markdown_file = tmp_path / "Calculus-16.md"
    next_file = tmp_path / "Calculus-17.md"
    markdown_file.write_text(
        "## 1.5\n## Using One-Sided Limits\nSection text.\n"
        "EXAMPLE 11 Find the limit.\n## SOLUTION\nWorked solution.\n"
        "1.6\n\nExercises\n1. Find another limit.\n",
        encoding="utf-8",
    )
    next_file.write_text(
        "<!-- extractor: mineru -->\n\n"
        "## 1.7 The Precise Definition of a Limit\nNext section text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([next_file, markdown_file])

    assert [chunk.kind for chunk in chunks] == [
        "section_text",
        "example",
        "exercises",
        "section_text",
    ]
    assert chunks[1].section == "1.5"
    assert "Worked solution." in chunks[1].text
    assert "Exercises" not in chunks[1].text
    assert chunks[2].section == "1.6"
    assert chunks[2].section_title == "Exercises"
    assert "1. Find another limit." in chunks[2].text
    assert chunks[2].source_files == ("Calculus-16.md",)
    assert chunks[3].section == "1.7"
    assert "Next section text." in chunks[3].text


def test_plain_section_number_and_exercises_can_cross_files(tmp_path):
    first_file = tmp_path / "part-1.md"
    second_file = tmp_path / "part-2.md"
    first_file.write_text(
        "## 1.5\nPrevious section.\n1.6\n<!-- extractor: mineru -->\n",
        encoding="utf-8",
    )
    second_file.write_text(
        "<!-- extractor: mineru -->\n\nExercises\n1. Find the limit.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([second_file, first_file])

    exercise_chunk = next(chunk for chunk in chunks if chunk.kind == "exercises")
    assert exercise_chunk.section == "1.6"
    assert exercise_chunk.section_title == "Exercises"
    assert "1. Find the limit." in exercise_chunk.text
    assert exercise_chunk.source_files == ("part-1.md", "part-2.md")


def test_exercises_heading_on_section_line_creates_exercise_chunk(tmp_path):
    markdown_file = tmp_path / "exercises.md"
    markdown_file.write_text(
        "## 1.1 Exercises\n1. Find the limit.\n1.2 Evaluate another limit.\n"
        "1.3\n## Next Section\nNext section text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert [chunk.kind for chunk in chunks] == ["exercises", "section_text"]
    assert chunks[0].section == "1.1"
    assert chunks[0].section_title == "Exercises"
    assert "1. Find the limit." in chunks[0].text
    assert "1.2 Evaluate another limit." in chunks[0].text
    assert chunks[1].section == "1.3"
    assert chunks[1].section_title == "Next Section"


def test_table_of_contents_section_with_trailing_page_number_is_skipped(tmp_path):
    markdown_file = tmp_path / "contents.md"
    markdown_file.write_text(
        "## 7.8 Improper Integrals 580\nTable of contents text.\n"
        "## 1.1\n## First Section\nReal section text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert len(chunks) == 1
    assert chunks[0].section == "1.1"
    assert "Table of contents text." not in chunks[0].text


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_structural_markers_inside_fenced_code_are_ignored(tmp_path, fence):
    markdown_file = tmp_path / "fenced.md"
    markdown_file.write_text(
        "## 1.1\nSection introduction.\n"
        f"{fence}markdown\n## 9.9 Fake section\nEXAMPLE 8 Fake example.\n{fence}\n"
        "More section text.\nEXAMPLE 1 Real example.\n## SOLUTION\nAnswer.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert [chunk.kind for chunk in chunks] == ["section_text", "example"]
    assert chunks[0].section == "1.1"
    assert "## 9.9 Fake section" in chunks[0].text
    assert "EXAMPLE 8 Fake example." in chunks[0].text
    assert "EXAMPLE 1 Real example." in chunks[1].text
    assert "Answer." in chunks[1].text


def test_four_space_indented_fence_does_not_hide_real_example(tmp_path):
    markdown_file = tmp_path / "indented-fence.md"
    markdown_file.write_text(
        "## 1.1\nSection introduction.\n    ```markdown\n"
        "EXAMPLE 1 Real example.\n## SOLUTION\nAnswer.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert [chunk.kind for chunk in chunks] == ["section_text", "example"]
    assert "EXAMPLE 1 Real example." in chunks[1].text


def test_four_space_indented_example_marker_is_not_a_chunk_boundary(tmp_path):
    markdown_file = tmp_path / "indented-example.md"
    markdown_file.write_text(
        "## 1.1\nSection text.\n    EXAMPLE 1 is a code sample.\n"
        "More section text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert len(chunks) == 1
    assert chunks[0].kind == "section_text"
    assert "EXAMPLE 1 is a code sample." in chunks[0].text


def test_backtick_in_fence_info_does_not_open_a_fence(tmp_path):
    markdown_file = tmp_path / "invalid-fence.md"
    markdown_file.write_text(
        "## 1.1\nSection introduction.\n```language`\n"
        "EXAMPLE 1 Real example.\n## SOLUTION\nAnswer.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert [chunk.kind for chunk in chunks] == ["section_text", "example"]
    assert "```language`" in chunks[0].text
    assert "EXAMPLE 1 Real example." in chunks[1].text


def test_image_placeholder_is_readable_and_figure_caption_is_kept(tmp_path):
    markdown_file = tmp_path / "figures.md"
    markdown_file.write_text(
        "## 1.1\n## Functions\n## FIGURE 1\nVertical acceleration graph\n"
        "<!-- image -->\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert len(chunks) == 1
    assert "FIGURE 1" in chunks[0].text
    assert "Vertical acceleration graph" in chunks[0].text
    assert "[圖片未擷取]" in chunks[0].text
    assert "<!-- image -->" not in chunks[0].text


def test_jsonl_records_include_index_and_chunk_metadata(tmp_path):
    markdown_file = tmp_path / "section.md"
    output_file = tmp_path / "chunks.jsonl"
    markdown_file.write_text("## 2.1\nDefinition text.\n", encoding="utf-8")
    chunks = chunk_markdown_files([markdown_file])

    write_chunks_jsonl(chunks, output_file, [markdown_file])

    record = json.loads(output_file.read_text(encoding="utf-8").splitlines()[0])
    assert record["index"] == 1
    assert record["id"] == chunks[0].chunk_id
    assert record["kind"] == "section_text"
    assert record["section"] == "2.1"
    assert record["source_files"] == ["section.md"]
    assert record["source_spans"] == [
        {"file": "section.md", "start_line": 1, "end_line": 2}
    ]


def test_cli_refuses_to_overwrite_an_input_markdown_file(tmp_path, monkeypatch):
    markdown_file = tmp_path / "section.md"
    original_markdown = "## 2.1\nDefinition text.\n"
    markdown_file.write_text(original_markdown, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["chunk_markdown", "--input-dir", str(tmp_path), "--output", str(markdown_file)],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert markdown_file.read_text(encoding="utf-8") == original_markdown


def test_cli_reports_invalid_utf8_input_without_traceback(tmp_path, monkeypatch):
    markdown_file = tmp_path / "invalid.md"
    markdown_file.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(
        "sys.argv",
        ["chunk_markdown", "--input-dir", str(tmp_path), "--output", str(tmp_path / "chunks.jsonl")],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2


def test_jsonl_writer_refuses_to_overwrite_an_input_markdown_file(tmp_path):
    markdown_file = tmp_path / "section.md"
    original_markdown = "## 2.1\nDefinition text.\n"
    markdown_file.write_text(original_markdown, encoding="utf-8")
    chunks = chunk_markdown_files([markdown_file])

    with pytest.raises(ValueError, match="不能覆寫輸入 Markdown"):
        write_chunks_jsonl(chunks, markdown_file, [markdown_file])

    assert markdown_file.read_text(encoding="utf-8") == original_markdown


def test_jsonl_writer_requires_input_paths(tmp_path):
    with pytest.raises(ValueError, match="至少需要一個輸入 Markdown"):
        write_chunks_jsonl([], tmp_path / "chunks.jsonl", [])


def test_cli_refuses_to_overwrite_a_hard_link_to_input(tmp_path, monkeypatch):
    markdown_file = tmp_path / "section.md"
    hard_link = tmp_path / "chunks.jsonl"
    original_markdown = "## 2.1\nDefinition text.\n"
    markdown_file.write_text(original_markdown, encoding="utf-8")
    os.link(markdown_file, hard_link)
    monkeypatch.setattr(
        "sys.argv",
        ["chunk_markdown", "--input-dir", str(tmp_path), "--output", str(hard_link)],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert markdown_file.read_text(encoding="utf-8") == original_markdown
    assert hard_link.read_text(encoding="utf-8") == original_markdown


def test_cli_refuses_to_overwrite_a_symlink_to_input(tmp_path, monkeypatch):
    markdown_file = tmp_path / "section.md"
    symlink = tmp_path / "chunks.jsonl"
    original_markdown = "## 2.1\nDefinition text.\n"
    markdown_file.write_text(original_markdown, encoding="utf-8")
    symlink.symlink_to(markdown_file)
    monkeypatch.setattr(
        "sys.argv",
        ["chunk_markdown", "--input-dir", str(tmp_path), "--output", str(symlink)],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert markdown_file.read_text(encoding="utf-8") == original_markdown


def test_cli_atomically_replaces_output_path_swapped_to_input_symlink(tmp_path, monkeypatch):
    input_dir = tmp_path / "markdown"
    input_dir.mkdir()
    markdown_file = input_dir / "section.md"
    output_file = tmp_path / "chunks.jsonl"
    original_markdown = "## 2.1\nDefinition text.\n"
    markdown_file.write_text(original_markdown, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["chunk_markdown", "--input-dir", str(input_dir), "--output", str(output_file)],
    )
    original_chunker = chunker.chunk_markdown_files

    def add_symlink_after_validation(paths, *args, **kwargs):
        output_file.symlink_to(markdown_file)
        return original_chunker(paths, *args, **kwargs)

    monkeypatch.setattr(chunker, "chunk_markdown_files", add_symlink_after_validation)

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert markdown_file.read_text(encoding="utf-8") == original_markdown
    assert output_file.is_symlink()

TOC_TEXT = (
    "## Contents\n"
    "- 1.4 The Tangent and Velocity Problems 45\n"
    "- 1.5 The Limit of a Function 51\n"
    "- 1.6 Calculating Limits Using the Limit Laws 62\n"
    "3.7 Optimization Problems 265\n"
    "3.8 Newton's Method 280\n"
    "| 6.3 | Logarithmic Functions 433 | 6.3\\* | The Natural Exponential Function 460 |\n"
    "| 6.4 | Derivatives of Logarithmic Functions 440 | 6.4* | General Functions 468 |\n"
    "- 10.4 Calculus in Polar Coordinates 732\n"
    "- 10.5 Conic Sections 740\n"
)


def _chunk_with_toc(tmp_path, body):
    toc_file = tmp_path / "book-1.md"
    body_file = tmp_path / "book-2.md"
    toc_file.write_text(TOC_TEXT, encoding="utf-8")
    body_file.write_text(body, encoding="utf-8")
    return chunk_markdown_files([toc_file, body_file])


def test_toc_file_is_not_chunked(tmp_path):
    chunks = _chunk_with_toc(tmp_path, "## 1.4\n## The Tangent and Velocity Problems\nText.\n")

    assert [chunk.section for chunk in chunks] == ["1.4"]
    assert all("book-1.md" not in chunk.source_files for chunk in chunks)


def test_unnumbered_toc_title_starts_next_section_and_closes_example(tmp_path):
    chunks = _chunk_with_toc(
        tmp_path,
        "## 1.4\n## The Tangent and Velocity Problems\nIntro.\n"
        "EXAMPLE 1 Tangent.\n## SOLUTION\nAnswer.\n"
        "## The Limit of a Function\nLimit text.\n"
        "## Calculating Limits Using the Limit Laws\nLaws text.\n",
    )

    assert [(chunk.kind, chunk.section) for chunk in chunks] == [
        ("section_text", "1.4"),
        ("example", "1.4"),
        ("section_text", "1.5"),
        ("section_text", "1.6"),
    ]
    assert "Limit text." not in chunks[1].text
    assert chunks[2].section_title == "The Limit of a Function"
    assert chunks[2].text.startswith("## The Limit of a Function")


def test_title_of_a_non_upcoming_section_does_not_split(tmp_path):
    chunks = _chunk_with_toc(
        tmp_path,
        "## 1.4\n## The Tangent and Velocity Problems\nIntro.\n"
        "## Optimization Problems\nStill 1.4 text.\n",
    )

    assert [chunk.section for chunk in chunks] == ["1.4"]
    assert "Still 1.4 text." in chunks[0].text


def test_toc_title_can_skip_one_section_missing_from_the_body(tmp_path):
    chunks = _chunk_with_toc(
        tmp_path,
        "## 1.4\n## The Tangent and Velocity Problems\nIntro.\n"
        "## Calculating Limits Using the Limit Laws\nLaws text.\n",
    )

    assert [chunk.section for chunk in chunks] == ["1.4", "1.6"]
    assert "Laws text." in chunks[1].text


def test_number_only_line_followed_by_toc_title_starts_section(tmp_path):
    chunks = _chunk_with_toc(
        tmp_path,
        "3.7 Optimization Problems\nOptimize.\n\n3.8\n\nNewton's Method\nNewton text.\n",
    )

    assert [chunk.section for chunk in chunks] == ["3.7", "3.8"]
    assert chunks[1].section_title == "Newton's Method"
    assert chunks[1].text.startswith("3.8")
    assert "3.8" not in chunks[0].text


def test_escaped_star_section_follows_toc_page_order(tmp_path):
    chunks = _chunk_with_toc(
        tmp_path,
        "## 6.4 Derivatives of Logarithmic Functions\nLog text.\n"
        "6.3\\*\n\n## The Natural Exponential Function\nExp text.\n",
    )

    assert [chunk.section for chunk in chunks] == ["6.4", "6.3*"]
    assert chunks[1].section_title == "The Natural Exponential Function"
    assert "Exp text." in chunks[1].text


def test_toc_title_overrides_figure_heading_and_repeated_number_does_not_restart(tmp_path):
    chunks = _chunk_with_toc(
        tmp_path,
        "## 10.4\n## Calculus in Polar Coordinates\nPolar.\n"
        "## Conic Sections\n\n## 10.5\n\nConic intro.\n\n## FIGURE 1 Conics\nMore.\n",
    )

    assert [chunk.section for chunk in chunks] == ["10.4", "10.5"]
    assert chunks[1].section_title == "Conic Sections"
    assert "Conic intro." in chunks[1].text


def test_earlier_section_reference_does_not_restart_section(tmp_path):
    chunks = _chunk_with_toc(
        tmp_path,
        "## 10.5 Conic Sections\nConics.\n"
        "## Proofs of Theorems\nSection 1.6\n\nLimit Laws proof.\n## Section 1.4\nMore proof.\n",
    )

    assert [chunk.section for chunk in chunks] == ["10.5"]
    assert "More proof." in chunks[0].text


def test_toc_numbered_title_closes_previous_exercises(tmp_path):
    chunks = _chunk_with_toc(
        tmp_path,
        "## 1.4 Exercises\n1. A question.\n1.5 Evaluate another limit.\n"
        "1.5 The Limit of a Function\nLimit text.\n",
    )

    assert [(chunk.kind, chunk.section) for chunk in chunks] == [
        ("exercises", "1.4"),
        ("section_text", "1.5"),
    ]
    assert "1.5 Evaluate another limit." in chunks[0].text
    assert "Limit text." in chunks[1].text


def test_title_two_ahead_does_not_skip_a_section_numbered_in_the_body(tmp_path):
    toc_file = tmp_path / "book-1.md"
    body_file = tmp_path / "book-2.md"
    toc_file.write_text(
        "## Contents\n"
        "| 6.3 | Logarithmic Functions 433 | 6.2* | The Natural Logarithmic Function 451 |\n"
        "| 6.4 | Derivatives of Logarithmic Functions 440 | 6.3* | The Natural Exponential Function 460 |\n",
        encoding="utf-8",
    )
    body_file.write_text(
        "## 6.3 Logarithmic Functions\nLog text.\n"
        "## The Natural Logarithmic Function\nStill 6.3.\n"
        "## 6.4 Derivatives of Logarithmic Functions\nDerivative text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([toc_file, body_file])

    assert [chunk.section for chunk in chunks] == ["6.3", "6.4"]
    assert "Still 6.3." in chunks[0].text


APPENDIX_TOC_TEXT = (
    "## Contents\n"
    "- 16.9 The Divergence Theorem 1238\n"
    "## Appendixes\n"
    "A Numbers, Inequalities, and Absolute Values A2\n"
    "B Coordinate Geometry and Lines A10\n"
    "C Graphs of Second-Degree Equations A16\n"
    "F Proofs of Theorems A41\n"
)


def _chunk_appendix(tmp_path, body):
    toc_file = tmp_path / "book-1.md"
    body_file = tmp_path / "book-2.md"
    toc_file.write_text(APPENDIX_TOC_TEXT, encoding="utf-8")
    body_file.write_text(body, encoding="utf-8")
    return chunk_markdown_files([toc_file, body_file])


def test_appendixes_heading_closes_last_body_example_and_skips_overview_list(tmp_path):
    chunks = _chunk_appendix(
        tmp_path,
        "## 16.9 The Divergence Theorem\nDivergence.\n"
        "EXAMPLE 3 Flux.\n## SOLUTION\nAnswer.\n"
        "## Appendixes\n\nA Numbers, Inequalities, and Absolute Values\n"
        "B Coordinate Geometry and Lines\n\nA\n\n"
        "## Numbers, Inequalities, and Absolute Values\nReal numbers.\n",
    )

    assert [(chunk.part, chunk.kind, chunk.section) for chunk in chunks] == [
        ("body", "section_text", "16.9"),
        ("body", "example", "16.9"),
        ("appendix", "section_text", "A"),
    ]
    assert "Appendixes" not in chunks[1].text
    assert chunks[2].section_title == "Numbers, Inequalities, and Absolute Values"
    assert "B Coordinate Geometry and Lines" not in chunks[2].text
    assert "Real numbers." in chunks[2].text


def test_appendix_sections_examples_and_exercises_follow_toc_titles(tmp_path):
    chunks = _chunk_appendix(
        tmp_path,
        "## Appendixes\n"
        "## Numbers, Inequalities, and Absolute Values\nIntro A.\n"
        "## EXAMPLE 1 Solve the inequality.\nAnswer A1.\n"
        "1-12 Rewrite the expression.\n1. $|5 - 23|$\n13-38 Solve.\n"
        "## Coordinate Geometry and Lines\nIntro B.\n"
        "1. Two nonvertical lines are parallel if and only if they have the same slope.\n"
        "EXAMPLE 1 Describe the regions.\nAnswer B1.\n"
        "## Graphs of Second-Degree Equations\nIntro C.\n"
        "C Exercises\n1-4 Find an equation.\n",
    )

    assert [(chunk.kind, chunk.section) for chunk in chunks] == [
        ("section_text", "A"),
        ("example", "A"),
        ("exercises", "A"),
        ("section_text", "B"),
        ("example", "B"),
        ("section_text", "C"),
        ("exercises", "C"),
    ]
    assert all(chunk.part == "appendix" for chunk in chunks)
    assert "13-38 Solve." in chunks[2].text
    assert "1. Two nonvertical lines" in chunks[3].text
    assert chunks[4].section_title == "Coordinate Geometry and Lines"
    assert chunks[6].section_title == "Exercises"


def test_proofs_appendix_splits_on_section_references(tmp_path):
    chunks = _chunk_appendix(
        tmp_path,
        "## Appendixes\n## Proofs of Theorems\nWe prove theorems.\n"
        "Section 1.6\n\nLimit Laws proof.\n"
        "## Section 1.8\n\n8 Theorem continuity proof.\n",
    )

    assert [(chunk.section, chunk.section_title) for chunk in chunks] == [
        ("F", "Proofs of Theorems"),
        ("F", "Proofs of Theorems (Section 1.6)"),
        ("F", "Proofs of Theorems (Section 1.8)"),
    ]
    assert chunks[1].text.startswith("Section 1.6")
    assert "Limit Laws proof." in chunks[1].text
    assert "continuity proof." in chunks[2].text


def test_body_chunks_are_marked_as_body_in_jsonl(tmp_path):
    markdown_file = tmp_path / "section.md"
    output_file = tmp_path / "chunks.jsonl"
    markdown_file.write_text("## 2.1\nDefinition text.\n", encoding="utf-8")

    write_chunks_jsonl(chunk_markdown_files([markdown_file]), output_file, [markdown_file])

    assert json.loads(output_file.read_text(encoding="utf-8"))["part"] == "body"


def test_blue_subheading_ends_example_and_starts_section_text(tmp_path):
    from ingestion.subheadings import SubheadingIndex

    markdown_file = tmp_path / "cross.md"
    markdown_file.write_text(
        "## 12.4 The Cross Product\nIntro.\n"
        "EXAMPLE 2 Show that a x a = 0.\n## SOLUTION\nZero.\n"
        "## Limits and Technology\nMargin note stays in the example.\n"
        "## ■ Properties of the Cross Product\nProperties text.\n"
        "EXAMPLE 3 Find a perpendicular vector.\nAnswer.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files(
        [markdown_file], subheadings=SubheadingIndex(["Properties of the Cross Product"])
    )

    assert [(chunk.kind, chunk.section, chunk.section_title) for chunk in chunks] == [
        ("section_text", "12.4", "The Cross Product"),
        ("example", "12.4", "The Cross Product"),
        ("section_text", "12.4", "The Cross Product"),
        ("example", "12.4", "The Cross Product"),
    ]
    assert "Margin note stays in the example." in chunks[1].text
    assert chunks[2].text.startswith("## ■ Properties of the Cross Product")
    assert "Properties text." not in chunks[1].text


def test_blue_subheading_ends_appendix_example(tmp_path):
    from ingestion.subheadings import SubheadingIndex

    toc_file = tmp_path / "book-1.md"
    body_file = tmp_path / "book-2.md"
    toc_file.write_text("## Contents\n## Appendixes\nD Trigonometry A24\n", encoding="utf-8")
    body_file.write_text(
        "## Appendixes\n## Trigonometry\nAngles.\n"
        "EXAMPLE 7 Solve sin x = sin 2x.\nFive solutions.\n"
        "## The Law of Sines and the Law of Cosines\nLaw text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files(
        [toc_file, body_file],
        subheadings=SubheadingIndex(["The Law of Sines and the Law of Cosines"]),
    )

    assert [(chunk.part, chunk.kind, chunk.section) for chunk in chunks] == [
        ("appendix", "section_text", "D"),
        ("appendix", "example", "D"),
        ("appendix", "section_text", "D"),
    ]
    assert chunks[2].section_title == "Trigonometry"
    assert "Law text." in chunks[2].text


def test_blue_subheading_splits_section_text_but_not_a_heading_only_start(tmp_path):
    from ingestion.subheadings import SubheadingIndex

    markdown_file = tmp_path / "line-integrals.md"
    markdown_file.write_text(
        "## 16.3 The Fundamental Theorem for Line Integrals\n\n<!-- image -->\n\n"
        "## ■ Independence of Path\nPath text.\n"
        "## Limits and Technology\nMargin note.\n"
        "## ■ Conservative Vector Fields and Potential Functions\nThe question remains.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files(
        [markdown_file],
        subheadings=SubheadingIndex(
            ["Independence of Path", "Conservative Vector Fields and Potential Functions"]
        ),
    )

    assert [(chunk.kind, chunk.section) for chunk in chunks] == [
        ("section_text", "16.3"),
        ("section_text", "16.3"),
    ]
    assert "Path text." in chunks[0].text
    assert "Margin note." in chunks[0].text
    assert chunks[1].text.startswith("## ■ Conservative Vector Fields")
    assert chunks[1].section_title == "The Fundamental Theorem for Line Integrals"


def test_number_line_start_is_not_split_by_a_following_subheading(tmp_path):
    from ingestion.subheadings import SubheadingIndex

    toc_file = tmp_path / "book-1.md"
    markdown_file = tmp_path / "book-2.md"
    toc_file.write_text("## Contents\n4.2 The Definite Integral 314\n", encoding="utf-8")
    markdown_file.write_text(
        "4.2\n\n## The Definite Integral\nWe saw in Section 4.1.\n", encoding="utf-8"
    )

    chunks = chunk_markdown_files(
        [toc_file, markdown_file], subheadings=SubheadingIndex(["The Definite Integral"])
    )

    assert len(chunks) == 1
    assert chunks[0].text.startswith("4.2")


def test_heading_only_subsection_is_carried_into_the_next_example(tmp_path):
    from ingestion.subheadings import SubheadingIndex

    markdown_file = tmp_path / "rates.md"
    markdown_file.write_text(
        "## 2.7 Rates of Change\nIntro.\n"
        "EXAMPLE 5 Chemistry.\nAnswer five.\n"
        "## ■ Biology\n\n<!-- image -->\n\n"
        "EXAMPLE 6 Population growth.\nAnswer six.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file], subheadings=SubheadingIndex(["Biology"]))

    assert [chunk.kind for chunk in chunks] == ["section_text", "example", "example"]
    assert "Biology" not in chunks[1].text
    assert chunks[2].text.startswith("## ■ Biology")
    assert "EXAMPLE 6 Population growth." in chunks[2].text


def test_figure_caption_alone_does_not_count_as_section_body(tmp_path):
    from ingestion.subheadings import SubheadingIndex

    markdown_file = tmp_path / "curvature.md"
    markdown_file.write_text(
        "## 13.3 Arc Length and Curvature\n\nFIGURE 1\n\n<!-- image -->\n\n"
        "## ■ Arc Length\nLength text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file], subheadings=SubheadingIndex(["Arc Length"]))

    assert len(chunks) == 1
    assert "Length text." in chunks[0].text


def _layout(stem, items, body=()):
    from ingestion.exercise_layout import ExerciseLayout, line_key

    return ExerciseLayout(
        {stem: {"items": [[number, line_key(text)] for number, text in items], "body": [line_key(text) for text in body]}}
    )


def test_exercise_items_from_pdf_end_the_last_example(tmp_path):
    markdown_file = tmp_path / "book-30.md"
    markdown_file.write_text(
        "## 2.3 Differentiation Formulas\nIntro.\n"
        "EXAMPLE 13 At what points is the tangent horizontal?\nSOLUTION Answer.\n"
        "1. Table of formulas is body text.\n"
        "21. Find the derivative of the function.\n(b) Part two.\n22. Another exercise.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files(
        [markdown_file],
        exercise_layout=_layout("book-30", [(21, "Find the derivative"), (22, "Another exercise")]),
    )

    assert [(chunk.kind, chunk.section, chunk.section_title) for chunk in chunks] == [
        ("section_text", "2.3", "Differentiation Formulas"),
        ("example", "2.3", "Differentiation Formulas"),
        ("exercises", "2.3", "Exercises"),
    ]
    assert "1. Table of formulas" in chunks[1].text
    assert chunks[2].text.startswith("21. Find the derivative")
    assert "(b) Part two." in chunks[2].text


def test_body_numbered_list_is_not_treated_as_exercises(tmp_path):
    markdown_file = tmp_path / "book-81.md"
    markdown_file.write_text(
        "## 7.5 Strategy for Integration\nTable of Integration Formulas\n1. $\\int x^n dx$\n2. $\\int 1/x dx$\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file], exercise_layout=_layout("book-81", [(1, "Evaluate")]))

    assert [chunk.kind for chunk in chunks] == ["section_text"]


def test_exercises_after_next_section_heading_return_to_previous_section(tmp_path):
    first = tmp_path / "book-178.md"
    second = tmp_path / "book-179.md"
    first.write_text("## 16.6 Parametric Surfaces\nSurfaces.\n## 16.6 Exercises\n1. First exercise.\n", encoding="utf-8")
    second.write_text(
        "59. Show that the ellipsoid.\n"
        "## 16.7 Surface Integrals\n"
        "60. (a) Show that the hyperboloid.\n(b) Graph it.\n\n<!-- image -->\n\n"
        "61. Find the area of the sphere.\n"
        "The relationship between surface integrals and surface area.\n"
        "## ■ Parametric Surfaces\nMore text.\n",
        encoding="utf-8",
    )
    from ingestion.exercise_layout import ExerciseLayout, line_key

    layout = ExerciseLayout(
        {
            "book-179": {
                "items": [[59, line_key("Show that the ellipsoid")], [60, line_key("(a) Show that the hyperboloid")], [61, line_key("Find the area of the sphere")]],
                "body": [line_key("The relationship between surface integrals")],
            }
        }
    )

    chunks = chunk_markdown_files([first, second], exercise_layout=layout)

    assert [(chunk.kind, chunk.section) for chunk in chunks] == [
        ("section_text", "16.6"),
        ("exercises", "16.6"),
        ("section_text", "16.7"),
    ]
    exercises = chunks[1].text
    assert "1. First exercise." in exercises and "59. Show" in exercises and "61. Find" in exercises
    assert "(b) Graph it." in exercises
    assert "16.7" not in exercises
    assert chunks[2].text.startswith("## 16.7 Surface Integrals")
    assert "The relationship between surface integrals" in chunks[2].text
    assert chunks[2].section_title == "Surface Integrals"


def test_toc_heading_after_exercises_starts_section_even_if_it_matches_body_text(tmp_path):
    from ingestion.exercise_layout import ExerciseLayout, line_key

    toc_file = tmp_path / "book-1.md"
    body_file = tmp_path / "book-176.md"
    toc_file.write_text(
        "## Contents\n16.5 Curl and Divergence 1178\n16.6 Parametric Surfaces and Their Areas 1190\n",
        encoding="utf-8",
    )
    body_file.write_text(
        "## 16.5 Exercises\n41. We have seen that all vector fields.\n"
        "## Parametric Surfaces and Their Areas\nSo far we have considered special surfaces.\n",
        encoding="utf-8",
    )
    layout = ExerciseLayout(
        {
            "book-176": {
                "items": [[41, line_key("We have seen that all")]],
                "body": [line_key("Parametric Surfaces and Their Areas"), line_key("So far we have considered")],
            }
        }
    )

    chunks = chunk_markdown_files([toc_file, body_file], exercise_layout=layout)

    assert [(chunk.kind, chunk.section) for chunk in chunks] == [
        ("exercises", "16.5"),
        ("section_text", "16.6"),
    ]
    assert chunks[1].section_title == "Parametric Surfaces and Their Areas"


def test_project_or_chapter_heading_ends_exercises(tmp_path):
    markdown_file = tmp_path / "book-75.md"
    markdown_file.write_text(
        "## 6.8 Exercises\n1. First exercise.\n## 13-16\n13. Range exercise.\n"
        "## APPLIED PROJECT\nProject text.\n",
        encoding="utf-8",
    )

    chunks = chunk_markdown_files([markdown_file])

    assert [(chunk.kind, chunk.section) for chunk in chunks] == [
        ("exercises", "6.8"),
        ("section_text", "6.8"),
    ]
    assert "13. Range exercise." in chunks[0].text
    assert chunks[1].text.startswith("## APPLIED PROJECT")
