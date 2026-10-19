"""Find the textbook's blue ■ subheadings in the PDFs so chunking can end examples there.

MinerU turns every heading-like line into `##`, so blue subheadings, margin notes and
red-boxed theorem titles look the same in Markdown. In the PDF they differ: a blue
subheading is a ZapfDingbatsStd ■ followed by MyriadPro-Semibold text, while the
end-of-example ■ uses ZapfDingbatsITC and red boxes use MyriadPro-Bold.

The list is written by ingestion.pdf_layout (run with .venv-mineru, where pypdf lives).
"""

import json
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUBHEADINGS = PROJECT_ROOT / "data" / "subheadings.json"
SUBHEADING_BULLET_FONT = "ZapfDingbatsStd"
SUBHEADING_FONT = "MyriadPro-Semibold"
INLINE_MATH = re.compile(r"\$[^$]*\$")
HEADING_LINE = re.compile(r"^ {0,3}(?:#{1,6}\s+(?P<heading>.+)|(?P<bullet>■\s*.+))$")
# The PDF text stops where a heading continues in math (e.g. "The Number" + italic e).
ENDS_IN_MATH = re.compile(r"\$|[∞·]|\s[A-Za-z]\??$")


def heading_key(text: str) -> str:
    """Letters and digits only, so bullets, quotes, spacing and math do not matter."""
    without_math = INLINE_MATH.sub(" ", text)
    return re.sub(r"[^0-9a-z]", "", without_math.casefold())


def blue_subheadings(runs: list[tuple[str, str]]) -> list[str]:
    """Return the text of each subheading run that directly follows a blue ■ bullet."""
    headings = []
    for (previous_font, previous_text), (font, text) in zip(runs, runs[1:]):
        if (
            previous_font == SUBHEADING_BULLET_FONT
            and previous_text.strip() == "■"
            and font == SUBHEADING_FONT
            and heading_key(text)
        ):
            headings.append(" ".join(text.split()))
    return headings


class SubheadingIndex:
    """Recognise Markdown heading lines that are blue subheadings in the PDF."""

    def __init__(self, headings: list[str]) -> None:
        self._keys = frozenset(key for key in map(heading_key, headings) if key)

    def matches(self, line: str) -> bool:
        match = HEADING_LINE.match(line)
        if match is None or not self._keys:
            return False
        text = match.group("heading") or match.group("bullet")
        key = heading_key(text)
        if key in self._keys:
            return True
        return ENDS_IN_MATH.search(text) is not None and any(
            key.startswith(known) for known in self._keys
        )


def load_subheadings(path: Path) -> SubheadingIndex:
    """Load data/subheadings.json; without it no example is split at subheadings."""
    if not path.exists():
        return SubheadingIndex([])
    by_pdf: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
    return SubheadingIndex([heading for headings in by_pdf.values() for heading in headings])
