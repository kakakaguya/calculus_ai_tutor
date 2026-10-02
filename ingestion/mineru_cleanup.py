"""Fixes for systematic mistakes in MinerU's Markdown output.

Every rule targets an error pattern observed in the Calculus output and is written so a
correct construct with a similar shape (a real determinant, a real table) is left alone.
normalize_body is idempotent, so it can be re-applied to already-cleaned files.
"""

import re

PLACEHOLDER = "<!-- image -->"
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
HTML_IMAGE = re.compile(r"<img\b[^>]*>")
# The publisher's page footer, sometimes wrapped in <small><span ...>.
FOOTER_LINE = re.compile(r"^.*Copyright 2021 Cengage Learning\. All Rights Reserved\..*$\n?", re.M)
# MinerU's VLM writes \varliminf (lim with an underline) for an ordinary lim.
VARLIMINF = re.compile(r"\\varliminf(?![A-Za-z])")
BLANK_RUN = re.compile(r"\n{3,}")

# A gridded graph is sometimes read as a huge table of empty cells.
MARKDOWN_TABLE = re.compile(r"(?:^\|.*\|[ \t]*$\n?)+", re.M)
SEPARATOR_ROW = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+\s*$")
HTML_TABLE = re.compile(r"<table>.*?</table>", re.S)
HTML_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
MIN_GRAPH_CELLS = 20
MIN_EMPTY_RATIO = 0.9

# A multi-line derivation is sometimes wrapped in spurious |...| bars. A real determinant
# has no relation in its rows, so only arrays whose every row holds one are unwrapped.
WRAPPED_ARRAY = re.compile(
    r"\\left\|\s*(\\begin\{array\}\{[^}]*\}((?:(?!\\begin\{array\}).)*?)\\end\{array\})"
    r"\s*\\right[|.]", re.S)
ARRAY_SPEC = re.compile(r"^\\begin\{array\}\{[^}]*\}")
ROW_BREAK = re.compile(r"\\\\")
RELATION = re.compile(
    r"=|<|>|\\(?:approx|leq?|geq?|leqslant|geqslant|neq?|iff|Rightarrow|Longleftrightarrow|"
    r"equiv)(?![A-Za-z])")


def _is_misread_graph(cells: list[str]) -> bool:
    empty = sum(1 for cell in cells if not cell.strip())
    return len(cells) >= MIN_GRAPH_CELLS and empty / len(cells) >= MIN_EMPTY_RATIO


def _replace_markdown_table(match: re.Match) -> str:
    rows = [row for row in match.group(0).splitlines() if not SEPARATOR_ROW.match(row)]
    cells = [cell for row in rows for cell in row.strip().strip("|").split("|")]
    if not _is_misread_graph(cells):
        return match.group(0)
    return PLACEHOLDER + ("\n" if match.group(0).endswith("\n") else "")


def _replace_html_table(match: re.Match) -> str:
    cells = HTML_CELL.findall(match.group(0))
    return PLACEHOLDER if _is_misread_graph(cells) else match.group(0)


def _unwrap_derivation(match: re.Match) -> str:
    rows = [row for row in ROW_BREAK.split(match.group(2)) if row.strip()]
    if rows and all(RELATION.search(row) for row in rows):
        return match.group(1)
    return match.group(0)


def normalize_body(markdown: str) -> str:
    # Figures arrive as base64 images: useless for retrieval and they swamp the chunks.
    text = MARKDOWN_IMAGE.sub(PLACEHOLDER, markdown)
    text = HTML_IMAGE.sub(PLACEHOLDER, text)
    text = FOOTER_LINE.sub("", text)
    text = MARKDOWN_TABLE.sub(_replace_markdown_table, text)
    text = HTML_TABLE.sub(_replace_html_table, text)
    text = WRAPPED_ARRAY.sub(_unwrap_derivation, text)
    text = VARLIMINF.sub(r"\\lim", text)
    return BLANK_RUN.sub("\n\n", text).strip()
