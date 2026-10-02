from ingestion.ingest_mineru import (OUTPUT_MARKER, build_command, clean_markdown, is_current_output,
                           natural_key)


def test_embedded_images_become_placeholders():
    markdown = "text\n\n![](data:image/jpeg;base64,/9j/AAAA+/==)\n\nFIGURE 1"
    assert clean_markdown(markdown) == f"{OUTPUT_MARKER}\n\ntext\n\n<!-- image -->\n\nFIGURE 1\n"


def test_linked_images_become_placeholders():
    assert "<!-- image -->" in clean_markdown("![fig](images/a.jpg)")


def test_varliminf_is_read_as_lim():
    markdown = r"$$\varliminf_ {x \to a ^ {-}} f (x) = L$$"
    assert r"\lim_ {x \to a ^ {-}}" in clean_markdown(markdown)


def test_other_latex_is_untouched():
    markdown = r"$\lim_{x \to 0^{+}} \sqrt{x} = 0$ and $\varepsilon > 0$"
    assert markdown in clean_markdown(markdown)


def test_blank_line_runs_are_collapsed():
    assert "a\n\nb" in clean_markdown("a\n\n\n\n\nb")


def test_output_marker_identifies_current_output():
    assert is_current_output(clean_markdown("x"))
    assert not is_current_output("<!-- extractor: docling+pix2text -->\n\nx")


def test_natural_key_sorts_numbered_files():
    names = ["a-10.pdf", "a-2.pdf", "a-1.pdf"]
    assert sorted(names, key=natural_key) == ["a-1.pdf", "a-2.pdf", "a-10.pdf"]


def test_command_is_local_and_parses_every_page(tmp_path):
    command = build_command(tmp_path / "in.pdf", tmp_path / "out")
    assert "--remote" not in command
    assert command[command.index("--pages") + 1] == "all"
    assert command[command.index("--tier") + 1] == "standard"


# --- obvious-error cleanup (normalize_body is applied to new and existing output) ---
from ingestion.ingest_mineru import normalize_body

FOOTER = ("Copyright 2021 Cengage Learning. All Rights Reserved. May not be copied, scanned, "
          "or duplicated, in whole or in part. ... require it.")


def test_html_images_inside_tables_become_placeholders():
    body = '<td colspan="4"><img src="data:image/jpeg;base64,/9j/AA=="/> text</td>'
    assert normalize_body(body) == "<td colspan=\"4\"><!-- image --> text</td>"


def test_plain_copyright_footer_line_is_removed():
    assert normalize_body(f"before\n\n{FOOTER}\n\nafter") == "before\n\nafter"


def test_wrapped_copyright_footer_is_removed():
    body = f'a\n\n<small><span class="docvortex-page-footnote">{FOOTER}</span></small>\n\nb'
    assert normalize_body(body) == "a\n\nb"


def test_mostly_empty_markdown_table_is_a_misread_graph():
    rows = ["| y " + "|  " * 30 + "|", "| --- " * 31 + "|"] + ["|  " * 31 + "|"] * 10
    body = "text\n\n" + "\n".join(rows) + "\n\nmore"
    assert normalize_body(body) == "text\n\n<!-- image -->\n\nmore"


def test_real_markdown_table_is_kept():
    table = "| x | f(x) |\n| --- | --- |\n| 0.1 | 2.59 |\n|  | 2.70 |"
    assert normalize_body(table) == table


def test_mostly_empty_html_table_is_a_misread_graph():
    cells = "<tr>" + "<td></td>" * 3 + "</tr>"
    body = '<table><tr><td colspan="3">y</td></tr>' + cells * 20 + "</table>"
    assert normalize_body(body) == "<!-- image -->"


def test_real_html_table_is_kept():
    table = "<table><tr><td>Ellipsoid</td><td>$x^2 = 1$</td></tr><tr><td></td><td>Cone</td></tr></table>"
    assert normalize_body(table) == table


def test_derivation_wrapped_in_absolute_bars_is_unwrapped():
    body = (r"\left| \begin{array}{l} f'(x) = a \\ = b + c \\ \approx d \end{array} \right|")
    assert normalize_body(body) == r"\begin{array}{l} f'(x) = a \\ = b + c \\ \approx d \end{array}"


def test_unwrap_also_handles_right_dot_and_multiple_columns():
    body = r"\left| \begin{array}{c c} f(8) = 2 & g = 1 \\ h \leqslant 3 & k = 4 \end{array} \right."
    assert normalize_body(body) == r"\begin{array}{c c} f(8) = 2 & g = 1 \\ h \leqslant 3 & k = 4 \end{array}"


def test_determinant_is_kept():
    body = r"\left| \begin{array}{c c c} \mathbf{i} & \mathbf{j} & \mathbf{k} \\ 1 & 2 & 3 \\ 4 & 5 & 6 \end{array} \right|"
    assert normalize_body(body) == body


def test_wrapper_with_a_row_lacking_a_relation_is_kept():
    body = r"\left| \begin{array}{c} x + 1 \\ 1 - x = 2 \end{array} \right|"
    assert normalize_body(body) == body


def test_normalize_body_is_idempotent():
    body = (f"text\n\n{FOOTER}\n\n" r"\left| \begin{array}{l} a = b \end{array} \right|"
            "\n\n![](data:image/png;base64,AAA)")
    once = normalize_body(body)
    assert normalize_body(once) == once
