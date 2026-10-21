"""Split one chunk's text into embedding-sized segments without breaking its meaning.

Paragraphs are the unit: a display formula stays with the sentence that introduces it
and the "where ..." line that continues it, and a heading stays with the text below it.
Only a paragraph that is too long on its own is split, at sentence ends outside math.
"""

import math
import re


# Measured with nomic-embed-text on the section_text chunks (LaTeX makes it lower than prose).
CHARS_PER_TOKEN = 3.35
PARAGRAPH_BREAK = "\n\n"
DISPLAY_MATH = "$$"
# \$ is a currency sign ("\$9/meter"), not the start of math.
MATH_SPAN = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$|(?<!\\)\$(?:\\\$|[^$])*?(?<!\\)\$", re.S)
SENTENCE_BREAK = re.compile(r"(?<=[.?!;])\s+(?=[A-Z(\[$\\])")
HEADING_PARAGRAPH = re.compile(r"^ {0,3}(?:#{1,6}\s|■)[^\n]*$")
CONTINUATION = re.compile(r"^[a-z,.;:)]")


def estimate_tokens(text: str, chars_per_token: float = CHARS_PER_TOKEN) -> int:
    return math.ceil(len(text) / chars_per_token)


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, never cutting a $$ block that contains a blank line."""
    paragraphs: list[str] = []
    for part in text.split(PARAGRAPH_BREAK):
        part = part.strip()
        if not part:
            continue
        if paragraphs and paragraphs[-1].count(DISPLAY_MATH) % 2:
            paragraphs[-1] += PARAGRAPH_BREAK + part
        else:
            paragraphs.append(part)
    return paragraphs


def _blocks(paragraphs: list[str]) -> list[str]:
    """Glue paragraphs that only make sense together into one block."""
    blocks: list[str] = []
    after_heading = after_math = False
    for paragraph in paragraphs:
        is_math = paragraph.startswith(DISPLAY_MATH)
        continues = after_math and CONTINUATION.match(paragraph) is not None
        if blocks and (after_heading or is_math or continues):
            blocks[-1] += PARAGRAPH_BREAK + paragraph
        else:
            blocks.append(paragraph)
        after_heading = HEADING_PARAGRAPH.match(paragraph) is not None
        after_math = is_math
    return blocks


def _sentences(block: str) -> list[str]:
    math_spans = [match.span() for match in MATH_SPAN.finditer(block)]
    sentences: list[str] = []
    start = 0
    for match in SENTENCE_BREAK.finditer(block):
        if any(begin < match.start() < end for begin, end in math_spans):
            continue
        sentences.append(block[start:match.start()])
        start = match.end()
    sentences.append(block[start:])
    return sentences


def _pack(units: list[str], separator: str, max_tokens: int, chars_per_token: float) -> list[str]:
    """Greedily join units while the result stays within max_tokens."""
    packed: list[str] = []
    for unit in units:
        joined = packed[-1] + separator + unit if packed else unit
        if packed and estimate_tokens(joined, chars_per_token) <= max_tokens:
            packed[-1] = joined
        else:
            packed.append(unit)
    return packed


def _merge_short(segments: list[str], min_tokens: int, chars_per_token: float) -> list[str]:
    """Fold segments too small to retrieve on their own into a neighbour."""
    merged: list[str] = []
    for segment in segments:
        if merged and estimate_tokens(segment, chars_per_token) < min_tokens:
            merged[-1] += PARAGRAPH_BREAK + segment
        else:
            merged.append(segment)
    if len(merged) > 1 and estimate_tokens(merged[0], chars_per_token) < min_tokens:
        merged[:2] = [merged[0] + PARAGRAPH_BREAK + merged[1]]
    return merged


def segment_text(
    text: str,
    max_tokens: int,
    min_tokens: int,
    chars_per_token: float = CHARS_PER_TOKEN,
) -> tuple[str, ...]:
    """Return segments of about max_tokens; a formula longer than that stays whole."""
    if max_tokens <= 0 or not 0 <= min_tokens < max_tokens:
        raise ValueError(f"需要 0 <= min_tokens < max_tokens，收到 {min_tokens}、{max_tokens}")
    if chars_per_token <= 0:
        raise ValueError(f"chars_per_token 必須大於 0，收到 {chars_per_token}")
    if not text.strip():
        return ()
    if estimate_tokens(text.strip(), chars_per_token) <= max_tokens:
        return (text.strip(),)
    units: list[str] = []
    for block in _blocks(_paragraphs(text)):
        if estimate_tokens(block, chars_per_token) <= max_tokens:
            units.append(block)
        else:
            units.extend(_pack(_sentences(block), " ", max_tokens, chars_per_token))
    segments = _pack(units, PARAGRAPH_BREAK, max_tokens, chars_per_token)
    return tuple(_merge_short(segments, min_tokens, chars_per_token))
