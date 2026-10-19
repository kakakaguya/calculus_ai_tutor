"""Tell exercise items apart from body text using the PDF typesetting.

Exercise pages were removed from the split PDFs, but pages shared with an example or the
next section heading remain, and MinerU sometimes drops their "Exercises" label or reads
the next heading in the middle of them. In the PDF an exercise number ("21." or "1–4")
is MyriadPro-BoldSemiCn at 9 pt with 9 pt text, while body text is Times at 10 pt.

Each item is stored as its number plus a key: the letters of the text before the first
math, which MinerU writes as $...$. Items that start with math have an empty key and match
by number only when the Markdown line also starts with math.
"""

import json
from pathlib import Path
import re


ITEM_FONT_SUFFIX = "BoldSemiCn"
ITEM_SIZE = 9.0
BODY_SIZE = 10.0
SIZE_TOLERANCE = 0.3
ROMAN_FONTS = ("TimesLTStd-Roman", "TimesLTStd-Bold")
KEY_LENGTH = 16
MIN_ITEM_KEY = 6
MIN_BODY_KEY = 12
PDF_ITEM = re.compile(r"^(?P<number>\d{1,3})(?:\.|[–-]\d{1,3})$")
MARKDOWN_ITEM = re.compile(
    r"^ {0,3}(?:T\s+)?(?:#{1,6}\s*)?(?P<number>\d{1,3})(?:\.|\s*[–-]\s*\d{1,3})(?:\s+(?P<text>.*))?\s*$"
)

PART_LINE = re.compile(r"^ {0,3}\([a-z]{1,4}\)\s")

Run = tuple[str, float, str]


def line_key(text: str) -> str:
    """Letters before the first inline math, lower-cased and cut to a fixed length."""
    before_math = text.split("$", 1)[0]
    return re.sub(r"[^a-z]", "", before_math.casefold())[:KEY_LENGTH]


def _near(size: float, target: float) -> bool:
    return abs(size - target) <= SIZE_TOLERANCE


def _keys_agree(first: str, second: str, minimum: int) -> bool:
    shorter = min(len(first), len(second))
    return shorter >= minimum and first[:shorter] == second[:shorter]


def layout_from_runs(runs: list[Run]) -> dict[str, list]:
    """Exercise numbers with their keys, and keys of 10 pt body text, for one PDF."""
    items: list[list] = []
    body: list[str] = []
    for position, (font, size, text) in enumerate(runs):
        item_match = PDF_ITEM.match(text.strip())
        if font.endswith(ITEM_FONT_SUFFIX) and _near(size, ITEM_SIZE) and item_match:
            following = runs[position + 1] if position + 1 < len(runs) else ("", 0.0, "")
            key = line_key(following[2]) if following[0] in ROMAN_FONTS else ""
            items.append([int(item_match.group("number")), key])
        elif font in ROMAN_FONTS and _near(size, BODY_SIZE):
            key = line_key(text)
            if len(key) == KEY_LENGTH and key not in body:
                body.append(key)
    return {"items": items, "body": body}


class ExerciseLayout:
    """Per-PDF exercise numbers and body text, looked up by Markdown file stem."""

    def __init__(self, by_stem: dict[str, dict[str, list]]) -> None:
        self._items: dict[str, dict[int, list[str]]] = {}
        self._body: dict[str, frozenset[str]] = {}
        for stem, layout in by_stem.items():
            numbers: dict[int, list[str]] = {}
            for number, key in layout.get("items", []):
                numbers.setdefault(int(number), []).append(key)
            self._items[stem] = numbers
            self._body[stem] = frozenset(layout.get("body", []))

    def is_exercise_item(self, stem: str, line: str) -> bool:
        match = MARKDOWN_ITEM.match(line)
        if match is None:
            return False
        markdown_key = line_key(match.group("text") or "")
        for pdf_key in self._items.get(stem, {}).get(int(match.group("number")), []):
            if not pdf_key and not markdown_key:
                return True
            if _keys_agree(pdf_key, markdown_key, MIN_ITEM_KEY):
                return True
        return False

    def is_body_text(self, stem: str, line: str) -> bool:
        """Numbered and "(b)" lines are exercise text even when their wording also occurs
        in 10 pt body text ("Find an equation of the ellipse")."""
        if MARKDOWN_ITEM.match(line) or PART_LINE.match(line):
            return False
        key = line_key(line)
        if len(key) < MIN_BODY_KEY:
            return False
        return any(_keys_agree(key, body_key, MIN_BODY_KEY) for body_key in self._body.get(stem, ()))


def load_exercise_layout(path: Path) -> ExerciseLayout:
    """Load data/exercise_layout.json; without it exercises rely on Markdown labels only."""
    if not path.exists():
        return ExerciseLayout({})
    return ExerciseLayout(json.loads(path.read_text(encoding="utf-8")))
