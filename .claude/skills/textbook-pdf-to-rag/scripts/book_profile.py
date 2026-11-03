"""Load book_profile.json: the per-book patterns the generic scripts are driven by.

Missing keys fall back to DEFAULTS (patterns that fit many English textbooks), and every
regex is compiled once here so a typo fails before any file is touched.
See references/book-profile.md for what each key means and how to fill it in.
"""

import copy
import json
from pathlib import Path
import re

IMAGE_PLACEHOLDER = "<!-- image -->"
OUTPUT_MARKER = "<!-- extractor: mineru -->"

DEFAULTS: dict = {
    "book": "",
    "protected_files": [],
    "skip_files": [],
    "cleanup": {"delete_line_patterns": [], "replacements": []},
    "layout_markers": [],
    "chunking": {
        "section_heading": (
            r"^ {0,3}(?:#{1,6}\s+)?(?:Section\s+)?(?P<section>\d+\.\d+(?:\.\d+)?\\?\*?)"
            r"(?:\s+(?P<title>[A-Z].*?))?\s*$"
        ),
        "example_start": r"^ {0,3}(?:#{1,6}\s*)?EXAMPLE\s+(?P<label>\d+[A-Z]?)\b",
        "solution_marker": r"^ {0,3}(?:#{1,6}\s*)?SOLUTION\b",
        "exercises_start": r"^ {0,3}(?:#{1,6}\s*)?(?:[A-H]\s+)?EXERCISES\s*$",
        # Numbered exercise line in Markdown; confirmed against layout hints when available.
        "exercise_item": r"^ {0,3}(?:#{1,6}\s*)?(?P<number>\d{1,3})(?:\.|\s*[–-]\s*\d{1,3})(?:\s+(?P<text>.*))?$",
        "exercise_marker": "exercise_item",
        "appendix_start": r"^ {0,3}#{1,6}\s*Appendix(?:es)?\s*$",
        # Contents entry for an appendix: "A Numbers, Inequalities, and Absolute Values A2".
        "appendix_toc_entry": (
            r"^ {0,3}(?:#{1,6}\s*|-\s+)?(?P<section>[A-H])\s+(?P<title>[A-Z].*?)\s+A(?P<page>\d{1,3})\s*$"
        ),
        "subheading_line": r"^ {0,3}(?:#{1,6}\s*)?■\s*(?P<title>\S.*?)\s*$",
        "subheading_marker": "subheading",
        # Contents-page entry "4.5 The Substitution Rule 349" (also inside | table | cells).
        # At most two digits per level, so "802.11 Wireless LANs 557" is not section 802.11.
        "toc_entry": (
            r"(?<![\d.])(?P<section>\d{1,2}\.\d{1,2})(?P<star>\\?\*)?\s*\|?\s*"
            r"(?P<title>[A-Z][^|]*?)\s+(?P<page>\d{1,4})(?=\s|\||$)"
        ),
        # A chapter title: MinerU writes it with a single "#" ("# Computer Networks and the
        # Internet"). Its overview text, up to the first section, becomes a chapter_intro chunk.
        "chapter_heading": r"^ {0,3}#\s+(?:Chapter\s+\d+\s*[:.]?\s*)?(?P<title>[A-Z][^\n]*?)\s*$",
        # Boxed sidebars ("CASE HISTORY"). Off by default: books also put SOLUTION, FIGURE 3
        # or PROOF in caps. chunk_markdown.py lists caps headings that look like sidebars.
        "sidebar_heading": None,
        "join_broken_paragraphs": True,
        "toc_lookahead": 2,
        "title_from_next_heading": True,
        "image_text": "[圖片未擷取]",
    },
    "evidence": {},
}
CHUNKING_PATTERNS = ("section_heading", "example_start", "solution_marker", "exercises_start",
                     "exercise_item", "subheading_line", "toc_entry", "appendix_start",
                     "appendix_toc_entry", "chapter_heading", "sidebar_heading")


def _merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


CASE_SENSITIVE = {"chunking.sidebar_heading"}  # "all caps" must not match "A Human Analogy"


def _compile(pattern: str | None, where: str) -> re.Pattern | None:
    if not pattern:
        return None
    flags = re.MULTILINE if where in CASE_SENSITIVE else re.IGNORECASE | re.MULTILINE
    try:
        return re.compile(pattern, flags)
    except re.error as error:
        raise ValueError(f"book_profile {where} 的正規表示式有誤：{error}") from error


def load_profile(path: Path | None) -> dict:
    """Return the merged profile with compiled patterns under profile['compiled']."""
    raw: dict = {}
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"找不到書本設定檔：{path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
    profile = _merge(DEFAULTS, raw)
    cleanup = profile["cleanup"]
    profile["compiled"] = {
        "delete_lines": [_compile(p, "cleanup.delete_line_patterns")
                         for p in cleanup["delete_line_patterns"]],
        "replacements": [(_compile(p, "cleanup.replacements"), r)
                         for p, r in cleanup["replacements"]],
        **{name: _compile(profile["chunking"].get(name), f"chunking.{name}")
           for name in CHUNKING_PATTERNS},
    }
    return profile


def natural_key(name: str) -> list:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", name)]
