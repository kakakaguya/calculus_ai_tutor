"""Parse the book's table of contents so chunking can confirm section boundaries."""

from dataclasses import dataclass
import re


TOC_ENTRY = re.compile(
    r"(?<![\d.])(?P<section>\d+\.\d+)(?P<star>\\?\*)?\s*\|?\s*"
    r"(?P<title>[A-Z][^|]*?)\s+(?P<page>\d{1,4})(?=\s|\||$)"
)
APPENDIX_ENTRY = re.compile(
    r"^ {0,3}(?:#{1,6}\s*|-\s+)?(?P<section>[A-H])\s+(?P<title>[A-Z].*?)\s+A(?P<page>\d{1,3})\s*$"
)
CONTENTS_HEADING = re.compile(r"^ {0,3}#{1,6}\s*contents\s*$", re.IGNORECASE)
MIN_ENTRIES_FOR_TOC_FILE = 10
# The body may lack a section entirely (e.g. 3.6), so also accept the one after it
# unless the skipped section has its own numbered heading in the body.
UPCOMING_LOOKAHEAD = 2


@dataclass(frozen=True)
class TocEntry:
    section: str
    title: str
    page: int


def normalize_title(text: str) -> str:
    """Compare headings by words only, ignoring Markdown markers and case."""
    cleaned = text.strip().lstrip("#").replace("\\*", "*")
    return " ".join(cleaned.split()).casefold()


def _section_key(section: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", section))


def parse_toc_lines(lines: list[str]) -> tuple[TocEntry, ...]:
    """Return unique section entries ordered by page number."""
    entries: dict[str, TocEntry] = {}
    for line in lines:
        for match in TOC_ENTRY.finditer(line):
            section = match.group("section") + ("*" if match.group("star") else "")
            if section not in entries:
                entries[section] = TocEntry(
                    section=section,
                    title=" ".join(match.group("title").split()),
                    page=int(match.group("page")),
                )
    return tuple(sorted(entries.values(), key=lambda entry: entry.page))


def parse_appendix_lines(lines: list[str]) -> tuple[TocEntry, ...]:
    """Return appendix entries such as `A Numbers, ... A2`, keyed by letter."""
    entries: dict[str, TocEntry] = {}
    for line in lines:
        match = APPENDIX_ENTRY.match(line)
        if match and match.group("section") not in entries:
            entries[match.group("section")] = TocEntry(
                section=match.group("section"),
                title=" ".join(match.group("title").split()),
                page=int(match.group("page")),
            )
    return tuple(sorted(entries.values(), key=lambda entry: entry.page))


def _upcoming_titled(
    entries: tuple[TocEntry, ...],
    next_position: int,
    line: str,
    numbered_sections: frozenset[str],
    lookahead: int = UPCOMING_LOOKAHEAD,
) -> str | None:
    normalized = normalize_title(line)
    for entry in entries[next_position:next_position + lookahead]:
        if normalize_title(entry.title) == normalized:
            return entry.section
        if entry.section in numbered_sections:
            return None
    return None


def is_toc_file(lines: list[str]) -> bool:
    if any(CONTENTS_HEADING.match(line) for line in lines):
        return True
    entry_lines = sum(1 for line in lines if TOC_ENTRY.search(line))
    return entry_lines >= MIN_ENTRIES_FOR_TOC_FILE


class TableOfContents:
    """Section order and titles as printed in the book's contents pages."""

    def __init__(
        self, entries: tuple[TocEntry, ...], appendixes: tuple[TocEntry, ...] = ()
    ) -> None:
        self.entries = entries
        self.appendixes = appendixes
        self._position = {entry.section: index for index, entry in enumerate(entries)}
        self._appendix_position = {entry.section: index for index, entry in enumerate(appendixes)}
        self._titles = {entry.section: entry.title for entry in (*appendixes, *entries)}

    @property
    def has_appendixes(self) -> bool:
        return bool(self.appendixes)

    def title_for(self, section: str) -> str | None:
        return self._titles.get(section)

    def is_before(self, section: str, other: str) -> bool:
        """True when `section` comes earlier in the book than `other`."""
        if section in self._position and other in self._position:
            return self._position[section] < self._position[other]
        return _section_key(section) < _section_key(other)

    def upcoming_section_titled(
        self,
        line: str,
        current_section: str | None,
        numbered_sections: frozenset[str] = frozenset(),
    ) -> str | None:
        """Return an upcoming section when `line` is exactly its title.

        A section listed in `numbered_sections` is never skipped over, because the
        body will start it with its own number.
        """
        if current_section is None:
            next_position = 0
        elif current_section in self._position:
            next_position = self._position[current_section] + 1
        else:
            return None
        return _upcoming_titled(self.entries, next_position, line, numbered_sections)

    def upcoming_appendix_titled(self, line: str, current_appendix: str | None) -> str | None:
        """Return a later appendix letter when `line` is exactly its title.

        Appendix titles are distinctive, so any later appendix may match.
        """
        if current_appendix is None:
            next_position = 0
        elif current_appendix in self._appendix_position:
            next_position = self._appendix_position[current_appendix] + 1
        else:
            return None
        return _upcoming_titled(
            self.appendixes, next_position, line, frozenset(), lookahead=len(self.appendixes)
        )
