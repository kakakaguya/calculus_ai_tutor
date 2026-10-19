"""Split MinerU Markdown into section text and complete example/solution chunks."""

import argparse
from dataclasses import asdict, dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import tempfile

from ingestion.exercise_layout import MARKDOWN_ITEM, ExerciseLayout, load_exercise_layout
from ingestion.subheadings import DEFAULT_SUBHEADINGS, SubheadingIndex, load_subheadings
from ingestion.table_of_contents import (
    TableOfContents,
    is_toc_file,
    normalize_title,
    parse_appendix_lines,
    parse_toc_lines,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "markdown"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "chunks.jsonl"
DEFAULT_EXERCISE_LAYOUT = PROJECT_ROOT / "data" / "exercise_layout.json"
IMAGE_PLACEHOLDER = "<!-- image -->"
EXTRACTOR_MARKER = "<!-- extractor: mineru -->"
SECTION_MARKER = re.compile(
    r"^ {0,3}##\s+(?:Section\s+)?(?P<section>\d+\.\d+(?:\.\d+)*(?:\\?\*)?)"
    r"(?:\s+(?P<title>.*?))?\s*$",
    re.IGNORECASE,
)
PLAIN_SECTION_MARKER = re.compile(
    r"^ {0,3}(?P<section>\d+\.\d+(?:\.\d+)*(?:\\?\*)?)"
    r"(?:\s+(?P<title>.*?))?\s*$"
)
HEADING_MARKER = re.compile(r"^ {0,3}##\s+(?P<title>.+?)\s*$")
EXAMPLE_MARKER = re.compile(
    r"^ {0,3}(?:#{1,6}\s*)?EXAMPLE\s+(?P<number>\d+(?:\.\d+)*[A-Z]?)\b",
    re.IGNORECASE,
)
EXERCISES_MARKER = re.compile(r"^ {0,3}(?:##\s*)?EXERCISES\s*$", re.IGNORECASE)
SOLUTION_MARKER = re.compile(r"^ {0,3}##\s+SOLUTION\s*$", re.IGNORECASE)
TITLE_PAGE_NUMBER = re.compile(r"\s+\d{1,4}$")
FENCE_START = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
NUMBER_PARTS = re.compile(r"(\d+)")
FIGURE_OR_TABLE_HEADING = re.compile(r"^ {0,3}#{1,6}\s*(?:FIGURE|TABLE)\b", re.IGNORECASE)
FIGURE_CAPTION = re.compile(r"^ {0,3}FIGURE\s+\d+\s*$", re.IGNORECASE)
APPENDIXES_HEADING = re.compile(r"^ {0,3}#{1,6}\s*Appendixes\s*$", re.IGNORECASE)
APPENDIX_EXERCISES_MARKER = re.compile(r"^ {0,3}(?:##\s*)?[A-H]\s+EXERCISES\s*$", re.IGNORECASE)
# Appendixes A and B have no Exercises heading; their sets open with "1-12 Rewrite ...".
FIRST_EXERCISE_RANGE = re.compile(r"^ {0,3}1-\d+\s+\S")
PROOF_SECTION_MARKER = re.compile(
    r"^ {0,3}(?:##\s*)?Section\s+(?P<section>\d+\.\d+(?:\.\d+)*(?:\\?\*)?)\s*$",
    re.IGNORECASE,
)
BODY_PART = "body"
APPENDIX_PART = "appendix"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Chunk:
    index: int
    chunk_id: str
    kind: str
    part: str
    section: str | None
    section_title: str | None
    text: str
    source_files: tuple[str, ...]
    source_spans: tuple[dict[str, int | str], ...]


@dataclass
class _PendingChunk:
    kind: str
    section: str
    section_title: str | None
    part: str = BODY_PART
    lines: list[str] = field(default_factory=list)
    locations: list[tuple[str, int]] = field(default_factory=list)


def natural_key(name: str) -> list[str | int]:
    return [int(part) if part.isdigit() else part.casefold() for part in NUMBER_PARTS.split(name)]


def _section_number(match: re.Match[str]) -> str:
    return match.group("section").replace("\\*", "*")


def _has_body_text(lines: list[str]) -> bool:
    """True once a chunk holds more than headings, images and bare figure captions."""
    return any(
        line.strip()
        and not line.lstrip().startswith("#")
        and line.strip() != IMAGE_PLACEHOLDER
        and not FIGURE_CAPTION.match(line)
        for line in lines
    )


def _is_heading_only_subsection(
    pending: "_PendingChunk | None", subheadings: SubheadingIndex
) -> bool:
    """A blue subheading followed directly by an example, e.g. "■ Biology" then EXAMPLE 6."""
    return (
        pending is not None
        and pending.kind == "section_text"
        and subheadings.matches(pending.lines[0])
        and not _has_body_text(pending.lines[1:])
    )


def _numbered_sections(lines: list[str]) -> frozenset[str]:
    """Sections whose number appears on its own heading line somewhere in the body."""
    sections: set[str] = set()
    for line in lines:
        match = SECTION_MARKER.match(line) or PLAIN_SECTION_MARKER.match(line)
        if match and (match.re is SECTION_MARKER or match.group("title") is None):
            sections.add(_section_number(match))
    return frozenset(sections)


def _starts_new_section(
    toc: TableOfContents, section: str, current_section: str | None, pending: "_PendingChunk | None", kind: str
) -> bool:
    """Reject numbers that move backwards or repeat the section already being read."""
    if current_section is None:
        return True
    if toc.is_before(section, current_section):
        return False
    is_repeat = section == current_section and kind == "section_text"
    return not (is_repeat and pending is not None and pending.kind == "section_text")


def _source_spans(locations: list[tuple[str, int]]) -> tuple[dict[str, int | str], ...]:
    spans: list[dict[str, int | str]] = []
    for filename, line_number in locations:
        if (
            spans
            and spans[-1]["file"] == filename
            and spans[-1]["end_line"] == line_number - 1
        ):
            spans[-1]["end_line"] = line_number
        else:
            spans.append({"file": filename, "start_line": line_number, "end_line": line_number})
    return tuple(spans)


def _build_chunk(pending: _PendingChunk, index: int) -> Chunk:
    text = "\n".join(
        "[圖片未擷取]" if line.strip() == IMAGE_PLACEHOLDER else line
        for line in pending.lines
    ).strip()
    source_spans = _source_spans(
        [
            location
            for line, location in zip(pending.lines, pending.locations)
            if line.strip()
        ]
    )
    source_files = tuple(dict.fromkeys(str(span["file"]) for span in source_spans))
    return Chunk(
        index=index,
        chunk_id=f"chunk-{index:06d}",
        kind=pending.kind,
        part=pending.part,
        section=pending.section,
        section_title=pending.section_title,
        text=text,
        source_files=source_files,
        source_spans=source_spans,
    )


def chunk_markdown_files(
    paths: list[Path],
    subheadings: SubheadingIndex | None = None,
    exercise_layout: ExerciseLayout | None = None,
) -> list[Chunk]:
    """Return ordered section-text and example chunks from Markdown files.

    `subheadings` lists the PDF's blue ■ subheadings; each one starts a new section-text
    chunk, ending the example or subsection before it.
    """
    subheadings = subheadings or SubheadingIndex([])
    exercise_layout = exercise_layout or ExerciseLayout({})
    ordered_paths = sorted(paths, key=lambda path: natural_key(path.name))
    if not ordered_paths:
        return []
    resolved_paths = {path: path.resolve() for path in ordered_paths}
    common_root = Path(os.path.commonpath([str(path.parent) for path in resolved_paths.values()]))
    source_paths = {
        path: resolved_paths[path].relative_to(common_root).as_posix()
        for path in ordered_paths
    }
    lines_by_path = {
        path: path.read_text(encoding="utf-8").splitlines() for path in ordered_paths
    }
    toc_paths = [path for path in ordered_paths if is_toc_file(lines_by_path[path])]
    toc_lines = [line for path in toc_paths for line in lines_by_path[path]]
    toc = TableOfContents(parse_toc_lines(toc_lines), parse_appendix_lines(toc_lines))
    ordered_paths = [path for path in ordered_paths if path not in toc_paths]
    numbered_sections = _numbered_sections(
        [line for path in ordered_paths for line in lines_by_path[path]]
    )
    first_content_line = {
        path: next(
            (
                line
                for line in lines
                if line.strip() and line.strip() != EXTRACTOR_MARKER
            ),
            "",
        )
        for path, lines in lines_by_path.items()
    }
    emitted: list[_PendingChunk] = []
    pending: _PendingChunk | None = None
    current_section: str | None = None
    section_title: str | None = None
    current_section_title: str | None = None
    previous_section: str | None = None
    fresh_section: _PendingChunk | None = None
    # A section heading MinerU read in the middle of the previous section's exercises.
    deferred_heading: _PendingChunk | None = None
    fence_character: str | None = None
    fence_length = 0
    in_appendix = False

    def flush() -> None:
        nonlocal pending, deferred_heading
        if pending is not None and pending.lines:
            last = emitted[-1] if emitted else None
            continues_exercises = (
                last is not None
                and last.kind == pending.kind == "exercises"
                and (last.section, last.part) == (pending.section, pending.part)
            )
            if continues_exercises:
                last.lines.extend(pending.lines)
                last.locations.extend(pending.locations)
            else:
                emitted.append(pending)
        pending = None
        if deferred_heading is not None:
            emitted.append(deferred_heading)
            deferred_heading = None

    def append_line(path: Path, line_number: int, line: str) -> None:
        nonlocal pending
        if current_section is None:
            return
        if pending is None:
            pending = _PendingChunk(
                "section_text", current_section, section_title, current_part()
            )
        pending.lines.append(line)
        pending.locations.append((source_paths[path], line_number))

    def current_part() -> str:
        return APPENDIX_PART if in_appendix else BODY_PART

    def open_chunk(
        path: Path, line_number: int, line: str, kind: str, section: str, title: str | None
    ) -> None:
        nonlocal pending, current_section, section_title
        flush()
        current_section = section
        section_title = title
        pending = _PendingChunk(kind, section, title, current_part())
        pending.lines.append(line)
        pending.locations.append((source_paths[path], line_number))

    def start_section(
        path: Path, line_number: int, line: str, section: str, title: str | None
    ) -> None:
        nonlocal previous_section, current_section_title, fresh_section
        if section != current_section:
            previous_section = current_section
        if title is not None and title.casefold() == "exercises":
            open_chunk(path, line_number, line, "exercises", section, title)
            return
        current_section_title = toc.title_for(section) or title
        open_chunk(path, line_number, line, "section_text", section, current_section_title)
        fresh_section = pending

    def start_exercises(path: Path, line_number: int, line: str) -> None:
        """Open exercises at a PDF-confirmed item; items right after a new section
        heading still belong to the previous section."""
        nonlocal pending, deferred_heading
        heading_only = (
            pending is not None
            and pending is fresh_section
            and previous_section is not None
            and not _has_body_text(pending.lines[1:])
        )
        if not heading_only:
            open_chunk(path, line_number, line, "exercises", current_section, "Exercises")
            return
        held, pending = pending, None
        flush()
        deferred_heading = held
        pending = _PendingChunk("exercises", previous_section, "Exercises", current_part())
        pending.lines.append(line)
        pending.locations.append((source_paths[path], line_number))

    def end_exercises(path: Path, line_number: int, line: str) -> None:
        """Body text after exercises: resume the held-back heading or this section's text."""
        nonlocal pending, deferred_heading, section_title
        resumed, deferred_heading = deferred_heading, None
        flush()
        section_title = current_section_title
        pending = resumed or _PendingChunk(
            "section_text", current_section, current_section_title, current_part()
        )
        pending.lines.append(line)
        pending.locations.append((source_paths[path], line_number))

    def starts_subsection(path: Path, line_number: int, line: str) -> bool:
        """A blue subheading ends an example, or splits section text that already has body text."""
        if pending is None or not subheadings.matches(line):
            return False
        splits_text = pending.kind == "section_text" and _has_body_text(pending.lines[1:])
        if pending.kind != "example" and not splits_text:
            return False
        open_chunk(
            path, line_number, line, "section_text", pending.section, pending.section_title
        )
        return True

    def open_example(path: Path, line_number: int, line: str, title: str | None) -> None:
        """Start an example, keeping a heading-only subsection in front of it."""
        nonlocal pending
        carried = pending if _is_heading_only_subsection(pending, subheadings) else None
        if carried is None:
            flush()
        pending = _PendingChunk("example", current_section, title, current_part())
        if carried is not None:
            pending.lines.extend(carried.lines)
            pending.locations.extend(carried.locations)
        pending.lines.append(line)
        pending.locations.append((source_paths[path], line_number))

    def handle_appendix_line(path: Path, line_number: int, line: str) -> None:
        letter = toc.upcoming_appendix_titled(line, current_section)
        if letter is not None:
            open_chunk(path, line_number, line, "section_text", letter, toc.title_for(letter))
            return
        if current_section is None:
            return
        appendix_title = toc.title_for(current_section)
        if starts_subsection(path, line_number, line):
            return
        proof_match = PROOF_SECTION_MARKER.match(line)
        if proof_match:
            title = f"{appendix_title} (Section {_section_number(proof_match)})"
            open_chunk(path, line_number, line, "section_text", current_section, title)
            return
        if EXAMPLE_MARKER.match(line):
            open_example(path, line_number, line, appendix_title)
            return
        starts_exercises = (
            EXERCISES_MARKER.match(line)
            or APPENDIX_EXERCISES_MARKER.match(line)
            or FIRST_EXERCISE_RANGE.match(line)
        )
        if starts_exercises and (pending is None or pending.kind != "exercises"):
            open_chunk(path, line_number, line, "exercises", current_section, "Exercises")
            return
        append_line(path, line_number, line)

    for path_index, path in enumerate(ordered_paths):
        lines = lines_by_path[path]
        for line_index, line in enumerate(lines):
            line_number = line_index + 1
            if fence_character is not None:
                append_line(path, line_number, line)
                closing_fence = re.match(
                    rf"^ {{0,3}}{re.escape(fence_character)}{{{fence_length},}}\s*$", line
                )
                if closing_fence:
                    fence_character = None
                    fence_length = 0
                continue

            fence_match = FENCE_START.match(line)
            if fence_match:
                append_line(path, line_number, line)
                fence = fence_match.group(1)
                if fence.startswith("`") and "`" in fence_match.group(2):
                    continue
                fence_character = fence[0]
                fence_length = len(fence)
                continue

            if line.strip() == EXTRACTOR_MARKER:
                continue

            if toc.has_appendixes and APPENDIXES_HEADING.match(line):
                flush()
                in_appendix = True
                current_section = None
                section_title = None
                continue

            if in_appendix:
                handle_appendix_line(path, line_number, line)
                continue

            if current_section is not None:
                in_exercises = pending is not None and pending.kind == "exercises"
                if not in_exercises and exercise_layout.is_exercise_item(path.stem, line):
                    start_exercises(path, line_number, line)
                    continue
                is_heading = line.lstrip().startswith("#")
                if in_exercises and not is_heading and exercise_layout.is_body_text(path.stem, line):
                    end_exercises(path, line_number, line)
                    continue

            toc_section = toc.upcoming_section_titled(line, current_section, numbered_sections)
            if toc_section is not None:
                start_section(path, line_number, line, toc_section, None)
                continue

            plain_section_match = PLAIN_SECTION_MARKER.match(line)
            if plain_section_match:
                section = _section_number(plain_section_match)
                title = plain_section_match.group("title")
                next_nonempty_line = next(
                    (
                        candidate
                        for candidate in lines[line_index + 1:]
                        if candidate.strip() and candidate.strip() != EXTRACTOR_MARKER
                    ),
                    "",
                )
                if not next_nonempty_line:
                    next_nonempty_line = next(
                        (
                            first_content_line[next_path]
                            for next_path in ordered_paths[path_index + 1:]
                            if first_content_line[next_path]
                        ),
                        "",
                    )
                next_line_is_exercises = EXERCISES_MARKER.match(next_nonempty_line) is not None
                toc_title = toc.title_for(section)
                next_line_is_toc_title = (
                    title is None
                    and toc_title is not None
                    and normalize_title(next_nonempty_line) == normalize_title(toc_title)
                )
                is_exercises_title = title is not None and title.casefold() == "exercises"
                is_later_section = (
                    current_section is not None
                    and title is None
                    and toc.is_before(current_section, section)
                )
                is_inside_exercises = pending is not None and pending.kind == "exercises"
                should_start_section = (
                    title is not None or next_line_is_exercises or next_line_is_toc_title
                )
                is_toc_heading = (
                    title is not None
                    and toc_title is not None
                    and normalize_title(title) == normalize_title(toc_title)
                )
                if is_inside_exercises:
                    should_start_section = is_exercises_title or is_later_section or is_toc_heading
                start_title = title or ("Exercises" if next_line_is_exercises else None)
                start_kind = "exercises" if start_title == "Exercises" or is_exercises_title else "section_text"
                if should_start_section and _starts_new_section(
                    toc, section, current_section, pending, start_kind
                ):
                    start_section(path, line_number, line, section, start_title)
                    continue

            section_match = SECTION_MARKER.match(line)
            if section_match:
                title = section_match.group("title")
                if current_section is None and title and TITLE_PAGE_NUMBER.search(title):
                    continue
                section = _section_number(section_match)
                kind = "exercises" if title and title.casefold() == "exercises" else "section_text"
                if _starts_new_section(toc, section, current_section, pending, kind):
                    start_section(path, line_number, line, section, title or None)
                    continue

            if starts_subsection(path, line_number, line):
                continue

            example_match = EXAMPLE_MARKER.match(line)
            if example_match:
                if current_section is None:
                    flush()
                    continue
                open_example(path, line_number, line, section_title)
                continue

            if EXERCISES_MARKER.match(line):
                if current_section is None:
                    continue
                if pending is None or pending.kind != "exercises":
                    flush()
                    section_title = "Exercises"
                    pending = _PendingChunk("exercises", current_section, section_title)
                append_line(path, line_number, line)
                continue

            if current_section is None:
                continue

            ends_exercises = (
                pending is not None
                and pending.kind == "exercises"
                and line.lstrip().startswith("#")
                and not MARKDOWN_ITEM.match(line)
                and not FIGURE_OR_TABLE_HEADING.match(line)
            )
            if ends_exercises:
                # A project or chapter-opening heading after the exercise list.
                end_exercises(path, line_number, line)
                continue

            append_line(path, line_number, line)
            heading_match = HEADING_MARKER.match(line)
            if section_title is None and heading_match and not SOLUTION_MARKER.match(line):
                section_title = heading_match.group("title")
                if pending.kind == "section_text":
                    pending.section_title = section_title

    flush()
    return [_build_chunk(chunk, index) for index, chunk in enumerate(emitted, 1)]


def write_chunks_jsonl(
    chunks: list[Chunk], output_path: Path, input_paths: list[Path]
) -> None:
    """Write chunks as UTF-8 JSON Lines without modifying source Markdown."""
    if not input_paths:
        raise ValueError("至少需要一個輸入 Markdown 路徑")
    validate_output_path(input_paths, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output_file:
            temporary_path = Path(output_file.name)
            for chunk in chunks:
                record = asdict(chunk)
                record["id"] = record.pop("chunk_id")
                output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def validate_output_path(markdown_paths: list[Path], output_path: Path) -> None:
    """Prevent the output file from replacing one of its Markdown inputs."""
    resolved_output = output_path.resolve()
    for path in markdown_paths:
        if path.resolve() == resolved_output or (
            output_path.exists() and output_path.samefile(path)
        ):
            raise ValueError(f"輸出路徑不能覆寫輸入 Markdown：{output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="依章節與例題切分 MinerU Markdown")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--subheadings",
        type=Path,
        default=DEFAULT_SUBHEADINGS,
        help="藍色小標題清單（由 ingestion.pdf_layout 產生）；例題遇到小標題就結束",
    )
    parser.add_argument(
        "--exercise-layout",
        type=Path,
        default=DEFAULT_EXERCISE_LAYOUT,
        help="PDF 習題題號與正文對照（由 ingestion.pdf_layout 產生）",
    )
    args = parser.parse_args()

    markdown_paths = list(args.input_dir.glob("*.md"))
    if not markdown_paths:
        parser.error(f"找不到 Markdown 檔案：{args.input_dir}")

    try:
        validate_output_path(markdown_paths, args.output)
    except ValueError as error:
        parser.error(str(error))

    try:
        subheadings = load_subheadings(args.subheadings)
        exercise_layout = load_exercise_layout(args.exercise_layout)
        chunks = chunk_markdown_files(markdown_paths, subheadings, exercise_layout)
        write_chunks_jsonl(chunks, args.output, markdown_paths)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    logger.info("已輸出 %s 個文字塊至 %s", len(chunks), args.output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()