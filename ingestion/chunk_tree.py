"""Link chunks into a tree: each example hangs under the subtopic text before it.

chunk_markdown starts a new section_text chunk at every blue ■ subheading, so the
section_text right before an example (same section and part) is the concept it applies.
"""

from collections import defaultdict
from dataclasses import dataclass
import re

from ingestion.chunk_markdown import EXAMPLE_MARKER


SECTION_TEXT = "section_text"
EXAMPLE = "example"
SECTION_OPENING = re.compile(
    r"^ {0,3}(?:#{1,6}\s*)?(?:Section\s+)?\d+\.\d+(?:\.\d+)*(?:\\?\*)?(?:\s|$)", re.IGNORECASE
)
HEADING_PREFIX = re.compile(r"^ {0,3}(?:#{1,6}\s*)?■?\s*")


@dataclass(frozen=True)
class ChunkNode:
    id: str
    index: int
    kind: str
    part: str
    section: str | None
    section_title: str | None
    subheading: str | None
    example_label: str | None
    parent_id: str | None
    child_ids: tuple[str, ...]
    segment_ids: tuple[str, ...]
    text: str
    source_files: tuple[str, ...]
    source_spans: tuple[dict, ...]


def _first_line(text: str) -> str:
    return next((line for line in text.splitlines() if line.strip()), "")


def subheading_of(text: str) -> str | None:
    """The subheading a section_text chunk opens with; None for a section's opening text."""
    line = _first_line(text)
    if SECTION_OPENING.match(line) or not line.lstrip().startswith(("#", "■")):
        return None
    return HEADING_PREFIX.sub("", line).strip() or None


def example_label(text: str) -> str | None:
    match = EXAMPLE_MARKER.match(_first_line(text))
    return f"Example {match.group('number')}" if match else None


def _parent_ids(rows: list[dict]) -> dict[str, str | None]:
    parents: dict[str, str | None] = {}
    concept: dict | None = None
    for row in rows:
        parent = None
        if row["kind"] == SECTION_TEXT:
            concept = row
        elif row["kind"] == EXAMPLE and concept is not None and (
            (concept["section"], concept["part"]) == (row["section"], row["part"])
        ):
            parent = concept["id"]
        parents[row["id"]] = parent
    return parents


def link_chunks(rows: list[dict]) -> tuple[ChunkNode, ...]:
    """Return the chunks in order with parent, children and inherited subheading."""
    parents = _parent_ids(rows)
    children: dict[str, list[str]] = defaultdict(list)
    for chunk_id, parent in parents.items():
        if parent is not None:
            children[parent].append(chunk_id)
    subheadings = {
        row["id"]: subheading_of(row["text"]) for row in rows if row["kind"] == SECTION_TEXT
    }
    return tuple(
        ChunkNode(
            id=row["id"],
            index=row["index"],
            kind=row["kind"],
            part=row["part"],
            section=row["section"],
            section_title=row["section_title"],
            subheading=subheadings.get(row["id"]) or subheadings.get(parents[row["id"]] or ""),
            example_label=example_label(row["text"]) if row["kind"] == EXAMPLE else None,
            parent_id=parents[row["id"]],
            child_ids=tuple(children.get(row["id"], ())),
            segment_ids=(),
            text=row["text"],
            source_files=tuple(row["source_files"]),
            source_spans=tuple(row["source_spans"]),
        )
        for row in rows
    )
