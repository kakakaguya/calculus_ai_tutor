#!/usr/bin/env python3
"""Split cleaned textbook Markdown into section_text / example / exercises chunks.

    python chunk_markdown.py work/markdown --profile work/book_profile.json \
        --hints work/layout_hints.json --out work/chunks.jsonl

Files are read in natural order as one stream, so an example that continues into the
next part file stays whole. A new section_text chunk starts at each section heading and
each subheading; an example runs from its EXAMPLE line until the next example,
subheading, section or exercises. Patterns come from book_profile.json.

What OCR does to headings, and how this copes:
- Cross references and page furniture look like headings ("Section 2.1"), so a section
  number is only trusted when it moves forward plausibly; rejected lines are reported.
- Numbers get dropped ("## The Limit of a Function"), so the contents pages are parsed
  and a heading equal to one of the next toc_lookahead titles starts that section.
- The "Exercises" label gets dropped, so a numbered line confirmed by the PDF's
  exercise-number font (layout hints) starts an exercises chunk.
- Appendices (after "## Appendixes") are lettered sections named only in the contents.
"""

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_profile import IMAGE_PLACEHOLDER, OUTPUT_MARKER, load_profile, natural_key  # noqa: E402
from stage_report import write_report  # noqa: E402

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^ {0,3}(?:#{1,6}\s+|■\s*)(?P<text>\S.*?)\s*$")
CONTENTS = re.compile(r"^ {0,3}#{1,6}\s*(?:table of\s+)?contents\s*$", re.IGNORECASE)
INLINE_MATH = re.compile(r"\$[^$]*\$")
HEADING_TEXT = re.compile(r"^ {0,3}#{1,6}\s*")
CONTINUATION = re.compile(r"^ {0,3}[a-z]")
CAPS_HEADING = re.compile(r"^ {0,3}#{1,6}\s*[A-Z][A-Z0-9 ,:&'’\-]{3,}\s*$")
KNOWN_CAPS = re.compile(r"^(?:SOLUTIONS?|EXAMPLES?|EXERCISES?|PROOF|DEFINITION|THEOREM|LEMMA|"
                        r"COROLLARY|NOTE|FIGURE|TABLE|CONTENTS|REVIEW|SUMMARY|INDEX|APPENDIX)\b")
# A paragraph that ends mid-sentence, continued in the next paragraph after a page break.
NOT_PROSE = re.compile(r"^(?:#|[-*•|$<\[]|\d+[.)]\s|(?:FIGURE|Figure|TABLE|Table)\b)")
MIN_BROKEN_PARAGRAPH = 120
DANGLING_WORD = re.compile(r"\b(?:the|a|an|of|to|in|for|with|by|from|on|at|into|onto|than|its|their)$")
MIN_TOC_LINES = 10  # a contents page without a "Contents" heading still has many entries
DEFAULT_MAX_JUMP = 3
KEY_LENGTH = 16
MIN_ITEM_KEY = 6


def heading_key(text: str) -> str:
    """Letters and digits only, so bullets, case, spacing and inline math do not matter."""
    return re.sub(r"[^0-9a-z]", "", INLINE_MATH.sub(" ", text).casefold())


def line_key(text: str) -> str:
    """Letters before the first inline math, for matching a line against PDF text."""
    return re.sub(r"[^a-z]", "", text.split("$", 1)[0].casefold())[:KEY_LENGTH]


def section_tuple(section: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", section))


def plausible_next(current: str | None, candidate: str, max_jump: int) -> bool:
    """Forward within the chapter by at most max_jump, or into one of the next chapters.

    A starred section ("6.2*", an alternative treatment) may restart within its chapter.
    """
    if current is None:
        return True
    now, new = section_tuple(current), section_tuple(candidate)
    if len(now) < 2 or len(new) < 2:
        return new > now
    if new[0] == now[0]:
        if candidate.endswith("*") and not current.endswith("*"):
            return True
        return now[1] < new[1] <= now[1] + max_jump
    return now[0] < new[0] <= now[0] + 2 and new[1] <= max_jump


def parse_toc(lines: list[str], pattern: re.Pattern | None) -> list[tuple[str, str]]:
    """(section, title) in page order; the first entry for a section wins."""
    if pattern is None:
        return []
    entries: dict[str, tuple[int, str]] = {}
    for line in lines:
        for match in pattern.finditer(line):
            section = match["section"] + ("*" if match.groupdict().get("star") else "")
            entries.setdefault(section, (int(match["page"]), " ".join(match["title"].split())))
    return [(section, title) for section, (_, title) in sorted(entries.items(), key=lambda e: e[1][0])]


def numbered_sections(lines: list[str], pattern: re.Pattern) -> frozenset[str]:
    """Sections whose number appears on a heading line somewhere in the body."""
    return frozenset(match["section"].replace("\\*", "*")
                     for line in lines if (match := pattern.match(line)))


def is_contents(lines: list[str], pattern: re.Pattern | None) -> bool:
    if any(CONTENTS.match(line) for line in lines[:15]):
        return True
    return pattern is not None and sum(1 for line in lines if pattern.search(line)) >= MIN_TOC_LINES


class ExerciseHints:
    """Exercise numbers (with the words that follow) per PDF stem, from layout hints."""

    def __init__(self, by_stem: dict[str, list[str]]) -> None:
        self._items: dict[str, dict[int, list[str]]] = {}
        for stem, entries in by_stem.items():
            numbers: dict[int, list[str]] = {}
            for entry in entries:
                match = re.match(r"\s*(\d+)\S*\s*(.*)", entry)
                if match:
                    numbers.setdefault(int(match[1]), []).append(line_key(match[2]))
            self._items[stem] = numbers

    def matches(self, stem: str, number: int, text: str) -> bool:
        markdown_key = line_key(text)
        for pdf_key in self._items.get(stem, {}).get(number, []):
            shorter = min(len(pdf_key), len(markdown_key))
            if (not pdf_key and not markdown_key) or (
                    shorter >= MIN_ITEM_KEY and pdf_key[:shorter] == markdown_key[:shorter]):
                return True
        return False


@dataclass
class Pending:
    kind: str
    part: str
    section: str
    title: str | None
    label: str | None = None
    lines: list[str] = field(default_factory=list)
    locations: list[tuple[str, int]] = field(default_factory=list)
    intro: bool = False  # chapter introduction: its section is known once the first section opens
    emitted: bool = False  # already in Chunker.emitted (a chunk resumed after a sidebar)


class Chunker:
    def __init__(self, profile: dict, hint_keys: frozenset[str] = frozenset(),
                 toc: list[tuple[str, str]] = (), appendix_toc: list[tuple[str, str]] = (),
                 exercises: ExerciseHints | None = None,
                 numbered: frozenset[str] = frozenset()) -> None:
        chunking = profile["chunking"]
        self._numbered = numbered
        self._patterns = profile["compiled"]
        self._title_next = chunking.get("title_from_next_heading", True)
        self._max_jump = chunking.get("max_section_jump", DEFAULT_MAX_JUMP)
        self._lookahead = chunking.get("toc_lookahead", 2)
        self._hint_keys = hint_keys
        self._toc = {"body": list(toc), "appendix": list(appendix_toc)}
        self._exercises = exercises or ExerciseHints({})
        self.part = "body"
        self.section: str | None = None
        self.title: str | None = None
        self._awaiting_title = False
        self._pending: Pending | None = None
        self._in_fence = False
        self.emitted: list[Pending] = []
        self.rejected: list[str] = []
        self.skipped_lines = 0
        self.toc_starts = 0
        self.exercise_starts = 0
        self.chapter_intros = 0
        self.sidebars = 0
        self.sidebar_candidates: dict[str, int] = {}
        self._resume_after_sidebar: Pending | None = None

    # -- chunk bookkeeping
    def _flush(self) -> None:
        pending, self._pending = self._pending, None
        if pending is None or not pending.lines or pending.emitted:
            return
        last = self.emitted[-1] if self.emitted else None
        if last and last.kind == pending.kind == "exercises" and (last.section, last.part) == (
                pending.section, pending.part):
            last.lines += pending.lines
            last.locations += pending.locations
        else:
            self.emitted.append(pending)

    def _start(self, kind: str, label: str | None = None) -> None:
        self._flush()
        self._pending = Pending(kind, self.part, self.section, self.title, label)

    def _append(self, where: tuple[str, int], line: str) -> None:
        if self._pending is None:
            self._start("section_text")
        self._pending.lines.append(line)
        self._pending.locations.append(where)

    def _open_section(self, where: tuple[str, int], line: str, number: str, title: str | None) -> None:
        intro = self._pending
        if intro is not None and intro.intro and intro.section is None:
            intro.section = number.split(".")[0]  # "1.1" opens chapter "1"
        self.section, self.title, self._awaiting_title = number, title, False
        self._start("section_text")
        self._append(where, line)

    # -- chapter introductions and sidebars
    def _start_intro(self, where: tuple[str, int], line: str, title: str | None) -> None:
        """Text between a chapter title and its first section (or before the first section of
        the book) is the chapter's overview; it becomes its own chunk instead of being dropped
        or glued to the previous chapter's last section."""
        self._flush()
        self._pending = Pending("section_text", self.part, None, title, "chapter_intro", intro=True)
        self.chapter_intros += 1
        self._append(where, line)

    def _sidebar_line(self, where: tuple[str, int], line: str) -> bool:
        """Boxed sidebars ("CASE HISTORY") become their own chunk. OCR often drops a sidebar
        into the middle of a body sentence; the body resumes with a lowercase continuation,
        which is put back into the interrupted chunk."""
        pattern = self._patterns["sidebar_heading"]
        pending = self._pending
        in_sidebar = pending is not None and pending.kind == "sidebar"
        if pattern and pattern.match(line):
            if not in_sidebar:
                self._resume_after_sidebar = pending
                self._flush()
                self._pending = Pending("sidebar", self.part, self.section, self.title,
                                        HEADING_TEXT.sub("", line).strip())
                self.sidebars += 1
            self._append(where, line)  # consecutive caps headings are the sidebar's title
            return True
        if not in_sidebar or not line.strip():
            return False
        if HEADING.match(line) and not _has_body(pending.lines):
            self._append(where, line)  # "## CASE HISTORY" / "## DATA CENTERS ...": a two-line title
            return True
        resume = self._resume_after_sidebar
        in_math = sum(l.count("$$") for l in pending.lines) % 2 == 1  # inside a $$ block
        if CONTINUATION.match(line) and resume is not None and not in_math:
            self._flush()
            resume.emitted = True
            self._pending, self._resume_after_sidebar = resume, None
            self._append(where, line)
            return True
        if HEADING.match(line):
            self._flush()  # the sidebar ends at the next heading; normal rules take over
            self._resume_after_sidebar = None
        return False

    # -- section detection
    def _toc_title(self, section: str) -> str | None:
        return next((title for s, title in self._toc["body"] if s == section), None)

    def _in_order(self, number: str) -> bool:
        """Follow the contents order when both sections are listed; otherwise plausibility."""
        sections = [section for section, _ in self._toc["body"]]
        if self.section in sections and number in sections:
            step = sections.index(number) - sections.index(self.section)
            return 0 < step <= self._max_jump
        return plausible_next(self.section, number, self._max_jump)

    def _try_section(self, where: tuple[str, int], line: str) -> bool:
        match = self._patterns["section_heading"].match(line)
        if not match:
            return False
        number = match["section"].replace("\\*", "*")
        if not self._in_order(number):
            if self.section is not None and section_tuple(number) != section_tuple(self.section):
                self.rejected.append(f"{where[0]}:{where[1]}  {line.strip()[:60]}")
            return False
        title = (match.groupdict().get("title") or "").strip() or None
        self._open_section(where, line, number, title or self._toc_title(number))
        self._awaiting_title = title is None and self._title_next
        return True

    def _try_toc_title(self, where: tuple[str, int], line: str) -> bool:
        """A heading equal to an upcoming section's title starts that section.

        A bulleted subheading line never does. Font hints are not used to exclude, since a
        section's opening title is often typeset like a subheading too. Instead the search
        stops at a section whose number appears in the body: that section will start at its
        own numbered heading, so a title match must not jump past it (a subsection of 6.3
        titled like section 6.2* would otherwise skip 6.4).
        """
        heading = HEADING.match(line)
        entries = self._toc[self.part]
        bulleted = self._patterns["subheading_line"] and self._patterns["subheading_line"].match(line)
        if not heading or not entries or bulleted:
            return False
        sections = [section for section, _ in entries]
        start = sections.index(self.section) + 1 if self.section in sections else 0
        if self.section is not None and self.section not in sections:
            return False
        # Appendix titles are distinctive, so any later appendix may match.
        window = entries[start:] if self.part == "appendix" else entries[start:start + self._lookahead]
        key = heading_key(heading["text"])
        for section, title in window:
            if heading_key(title) == key:
                self._open_section(where, line, section, title)
                self.toc_starts += 1
                return True
            if section in self._numbered:
                return False
        return False

    # -- other boundaries
    def _is_subheading(self, line: str) -> bool:
        if self._patterns["subheading_line"] and self._patterns["subheading_line"].match(line):
            return True
        heading = HEADING.match(line)
        return bool(heading and self._hint_keys and heading_key(heading["text"]) in self._hint_keys)

    def _is_exercise_item(self, filename: str, line: str) -> bool:
        if self._pending is not None and self._pending.kind == "exercises":
            return False
        match = self._patterns["exercise_item"] and self._patterns["exercise_item"].match(line)
        return bool(match) and self._exercises.matches(Path(filename).stem, int(match["number"]),
                                                       match.groupdict().get("text") or "")

    def feed(self, filename: str, number: int, line: str) -> None:
        where = (filename, number)
        if line.strip() == OUTPUT_MARKER:
            return  # each part file starts with it; it is not content of a chunk spanning files
        if FENCE.match(line):
            self._in_fence = not self._in_fence
        if self._in_fence:
            if self._pending is not None:
                self._append(where, line)
            return
        appendix_start = self._patterns["appendix_start"]
        if self.part == "body" and appendix_start and appendix_start.match(line):
            self._flush()
            self.part, self.section, self.title = "appendix", None, None
            return
        if self.part == "body" and self._try_section(where, line):
            return
        if self._awaiting_title and line.strip():
            self._awaiting_title = False
            heading = HEADING.match(line)
            if heading:
                if not self.title:
                    self.title = self._pending.title = heading["text"].lstrip("#■ ").strip()
                self._append(where, line)
                return
        if self._try_toc_title(where, line):
            return
        chapter = self._patterns["chapter_heading"]
        if self.part == "body" and chapter and (match := chapter.match(line)):
            self._start_intro(where, line, (match.groupdict().get("title") or "").strip() or None)
            return
        if self._sidebar_line(where, line):
            return
        if self._pending is not None and self._pending.intro:
            self._append(where, line)  # an overview is not split at its own subheadings
            return
        if self.section is None:
            if line.strip() and self.part == "body":
                self._start_intro(where, line, None)
            else:  # before the first appendix: the list of appendices, not content
                self.skipped_lines += bool(line.strip())
            return
        self._note_sidebar_candidate(line)
        example = self._patterns["example_start"] and self._patterns["example_start"].match(line)
        if self._patterns["exercises_start"] and self._patterns["exercises_start"].match(line):
            self._start("exercises")
        elif example:
            self._start("example", example.groupdict().get("label"))
        elif self._is_subheading(line):
            self._start("section_text")
        elif self._is_exercise_item(filename, line):
            self._start("exercises")
            self.exercise_starts += 1
        self._append(where, line)

    def _note_sidebar_candidate(self, line: str) -> None:
        """All-caps headings that are not a known structure word may be sidebars; reported so
        the profile's sidebar_heading can be set (it is off by default because books also
        use caps for SOLUTION, FIGURE 3, PROOF)."""
        if self._patterns["sidebar_heading"] or not CAPS_HEADING.match(line):
            return
        text = HEADING_TEXT.sub("", line).strip()
        if not KNOWN_CAPS.match(text):
            self.sidebar_candidates[text] = self.sidebar_candidates.get(text, 0) + 1

    def finish(self) -> list[Pending]:
        self._flush()
        return self.emitted


def _has_body(lines: list[str]) -> bool:
    return any(line.strip() and line.strip() != IMAGE_PLACEHOLDER and not HEADING.match(line)
               for line in lines)


def _spans(locations: list[tuple[str, int]]) -> list[dict]:
    spans: list[dict] = []
    for filename, number in locations:
        if spans and spans[-1]["file"] == filename and spans[-1]["end_line"] == number - 1:
            spans[-1]["end_line"] = number
        else:
            spans.append({"file": filename, "start_line": number, "end_line": number})
    return spans


def join_broken_paragraphs(text: str) -> tuple[str, int]:
    """Re-join a sentence that a page or file break split into two paragraphs.

    "No full stop at the end" is not enough: math books end a paragraph mid-sentence before
    a display formula ("the area is" / "3" / $$...$$). So a join needs a strong signal:
    the next paragraph starts in lowercase, or the previous one ends on an article or
    preposition, where no sentence can stop ("... so the" / "ISPs that provide ...").
    Headings, lists, tables, formulas and figure captions are never joined.
    """
    paragraphs = text.split("\n\n")
    out: list[str] = []
    joined = 0
    for paragraph in paragraphs:
        previous = out[-1] if out else ""
        stripped = paragraph.strip()
        continues = bool(re.match(r"[a-z]", stripped)) or (
            bool(re.match(r"[A-Z]\w*", stripped)) and DANGLING_WORD.search(previous) is not None)
        if (len(previous) >= MIN_BROKEN_PARAGRAPH and re.search(r"[A-Za-z,]$", previous)
                and not NOT_PROSE.match(previous) and continues and not NOT_PROSE.match(stripped)):
            out[-1] = f"{previous} {stripped}"
            joined += 1
        else:
            out.append(paragraph)
    return "\n\n".join(out), joined


def to_records(chunks: list[Pending], image_text: str, join: bool = True) -> tuple[list[dict], int]:
    records = []
    joined_total = 0
    for chunk in (chunk for chunk in chunks if _has_body(chunk.lines)):
        spans = _spans([where for line, where in zip(chunk.lines, chunk.locations) if line.strip()])
        text = "\n".join(image_text if line.strip() == IMAGE_PLACEHOLDER else line
                         for line in chunk.lines).strip()
        if join:
            text, joined = join_broken_paragraphs(text)
            joined_total += joined
        if chunk.intro and not chunk.title:
            chunk.title = next((HEADING_TEXT.sub("", l).strip() for l in chunk.lines if HEADING.match(l)), None)
        index = len(records) + 1
        records.append({
            "index": index, "id": f"chunk-{index:06d}", "kind": chunk.kind, "part": chunk.part,
            "section": chunk.section, "section_title": chunk.title, "label": chunk.label,
            "text": text, "source_files": list(dict.fromkeys(span["file"] for span in spans)),
            "source_spans": spans,
        })
    return records, joined_total


def load_hints(path: Path | None, chunking: dict) -> tuple[frozenset[str], ExerciseHints]:
    if path is None:
        return frozenset(), ExerciseHints({})
    hints = json.loads(path.read_text(encoding="utf-8"))
    subheadings = frozenset(key for by_marker in hints.values()
                            for text in by_marker.get(chunking["subheading_marker"], [])
                            if (key := heading_key(text)))
    exercises = ExerciseHints({stem: by_marker.get(chunking["exercise_marker"], [])
                               for stem, by_marker in hints.items()})
    return subheadings, exercises


def write_jsonl(records: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent,
                                         prefix=f".{output.name}.", delete=False)
    try:
        with handle:
            handle.writelines(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
        os.replace(handle.name, output)
    finally:
        Path(handle.name).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="依章節、小標題與例題切分教科書 Markdown")
    parser.add_argument("markdown_dir", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--hints", type=Path, help="extract_layout_hints.py 的輸出（可省略）")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", type=Path, help="同時把切塊統計與被拒絕的標題行寫成 JSON")
    args = parser.parse_args()
    try:
        profile = load_profile(args.profile)
        hint_keys, exercises = load_hints(args.hints, profile["chunking"])
    except (OSError, ValueError) as error:
        parser.error(str(error))
    patterns = profile["compiled"]
    paths = sorted(args.markdown_dir.glob("*.md"), key=lambda path: natural_key(path.name))
    if args.out.resolve() in {path.resolve() for path in paths}:
        parser.error("輸出路徑不能是輸入的 Markdown")
    texts = {path: path.read_text(encoding="utf-8").splitlines() for path in paths}
    contents = [path for path, lines in texts.items() if is_contents(lines, patterns["toc_entry"])]
    toc_lines = [line for path in contents for line in texts[path]]
    toc = parse_toc(toc_lines, patterns["toc_entry"])
    appendix_toc = parse_toc(toc_lines, patterns["appendix_toc_entry"])
    skip = set(profile["skip_files"])
    body_lines = [line for path, lines in texts.items()
                  if path not in contents and path.name not in skip for line in lines]
    chunker = Chunker(profile, hint_keys, toc, appendix_toc, exercises,
                      numbered_sections(body_lines, patterns["section_heading"]))
    skipped: list[str] = []
    for path, lines in texts.items():
        if path.name in skip or path in contents:
            print(f"略過（目錄或設定排除）：{path.name}")
            skipped.append(path.name)
            continue
        for number, line in enumerate(lines, 1):
            chunker.feed(path.name, number, line)
    chunking = profile["chunking"]
    records, joined = to_records(chunker.finish(), chunking["image_text"],
                                 chunking.get("join_broken_paragraphs", True))
    write_jsonl(records, args.out)
    kinds: dict[str, int] = {}
    for record in records:
        kinds[record["kind"]] = kinds.get(record["kind"], 0) + 1
    body = {r["section"] for r in records if r["part"] == "body" and r["label"] != "chapter_intro"}
    appendix = {r["section"] for r in records if r["part"] == "appendix"}
    print(f"{len(records)} 塊 {kinds}；本文 {len(body)} 節、附錄 {len(appendix)} 節 → {args.out}")
    print(f"目錄 {len(toc)} 節（附錄 {len(appendix_toc)}），{chunker.toc_starts} 節靠目錄標題辨認；"
          f"小標題提示 {len(hint_keys)} 個；{chunker.exercise_starts} 處靠題號字型辨認出習題")
    print(f"章導論 {chunker.chapter_intros} 塊；側欄 {chunker.sidebars} 個；"
          f"接回被分頁切斷的段落 {joined} 處")
    if chunker.sidebar_candidates:
        found = "、".join(f"{t}（{n}）" for t, n in sorted(chunker.sidebar_candidates.items(),
                                                          key=lambda item: -item[1])[:8])
        print(f"可能是側欄的全大寫標題（未設定 sidebar_heading，目前併在內文中）：{found}")
    if chunker.rejected:
        print(f"{len(chunker.rejected)} 行像章節標題但順序不合理，視為內文（前 10 筆）：")
        for line in chunker.rejected[:10]:
            print("  " + line)
    write_report(args.json, "chunk", ok=True, out=str(args.out), records=len(records), kinds=kinds,
                 body_sections=len(body), appendix_sections=len(appendix), toc_sections=len(toc),
                 appendix_toc_sections=len(appendix_toc), toc_title_starts=chunker.toc_starts,
                 subheading_hints=len(hint_keys), exercise_font_starts=chunker.exercise_starts,
                 chapter_intros=chunker.chapter_intros, sidebars=chunker.sidebars,
                 joined_paragraphs=joined, sidebar_candidates=chunker.sidebar_candidates,
                 rejected_headings=chunker.rejected, skipped_files=skipped)


if __name__ == "__main__":
    main()
