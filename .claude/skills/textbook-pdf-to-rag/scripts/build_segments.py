#!/usr/bin/env python3
"""chunks.jsonl -> chunk_tree.jsonl (whole chunks + parent links) + segments.jsonl (to embed).

    python build_segments.py work/chunks.jsonl --tree work/chunk_tree.jsonl \
        --segments work/segments.jsonl [--max-tokens 500] [--embed-kinds section_text]

Tree: each example gets parent_id = the section_text chunk right before it in the same
section (chunking starts a new section_text at every subheading, so that is the concept
the example applies), and every section_text lists its examples in child_ids.
Segments: only chunks of --embed-kinds are embedded. A chunk over --max-tokens is cut at
paragraph breaks (a $$ formula stays with its lead-in sentence and its "where ..."
continuation; a heading stays with what follows); only a paragraph that is too long by
itself is cut at sentence ends outside $...$. Each segment carries a header such as
"3.4 Limits at Infinity | Evaluating Limits" and points back to its whole chunk, so
retrieval matches a small segment and answers from the complete chunk.
"""

import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_report import write_report  # noqa: E402

CHARS_PER_TOKEN = 3.35  # measured with nomic-embed-text; re-measure for another model
MAX_TOKENS = 500
MIN_TOKENS = 100
EMBED_LIMIT_TOKENS = 2048
BREAK = "\n\n"
MATH_SPAN = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$|(?<!\\)\$(?:\\\$|[^$])*?(?<!\\)\$", re.S)
SENTENCE_END = re.compile(r"(?<=[.?!;])\s+(?=[A-Z(\[$\\])")
HEADING_PARAGRAPH = re.compile(r"^ {0,3}(?:#{1,6}\s|■)[^\n]*$")
CONTINUATION = re.compile(r"^[a-z,.;:)]")
# Exactly "3.4" (not "1.1.1", which some books use for numbered subsections).
SECTION_OPENING = re.compile(r"^ {0,3}(?:#{1,6}\s*)?(?:Section\s+)?\d+\.\d+(?![.\d])", re.IGNORECASE)
HEADING_PREFIX = re.compile(r"^ {0,3}(?:#{1,6}\s*)?■?\s*")
EXAMPLE_LABEL = re.compile(r"^ {0,3}(?:#{1,6}\s*)?EXAMPLE\s+(\d+[A-Z]?)\b", re.IGNORECASE)


def tokens(text: str, cpt: float) -> int:
    return math.ceil(len(text) / cpt)


# ---- segmenting -------------------------------------------------------------------------

def _paragraphs(text: str) -> list[str]:
    out: list[str] = []
    for part in (p.strip() for p in text.split(BREAK)):
        if not part:
            continue
        if out and out[-1].count("$$") % 2:  # never split inside a $$ block
            out[-1] += BREAK + part
        else:
            out.append(part)
    return out


def _blocks(paragraphs: list[str]) -> list[str]:
    blocks: list[str] = []
    after_heading = after_math = False
    for paragraph in paragraphs:
        is_math = paragraph.startswith("$$")
        glue = after_heading or is_math or (after_math and CONTINUATION.match(paragraph))
        if blocks and glue:
            blocks[-1] += BREAK + paragraph
        else:
            blocks.append(paragraph)
        after_heading, after_math = bool(HEADING_PARAGRAPH.match(paragraph)), is_math
    return blocks


def _sentences(block: str) -> list[str]:
    protected = [m.span() for m in MATH_SPAN.finditer(block)]
    pieces, start = [], 0
    for match in SENTENCE_END.finditer(block):
        if not any(a < match.start() < b for a, b in protected):
            pieces.append(block[start:match.start()])
            start = match.end()
    return pieces + [block[start:]]


def _pack(units: list[str], sep: str, limit: int, cpt: float) -> list[str]:
    packed: list[str] = []
    for unit in units:
        if packed and tokens(packed[-1] + sep + unit, cpt) <= limit:
            packed[-1] += sep + unit
        else:
            packed.append(unit)
    return packed


def segment_text(text: str, limit: int, minimum: int, cpt: float) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if tokens(text, cpt) <= limit:
        return [text]
    units: list[str] = []
    for block in _blocks(_paragraphs(text)):
        units += [block] if tokens(block, cpt) <= limit else _pack(_sentences(block), " ", limit, cpt)
    merged: list[str] = []
    for segment in _pack(units, BREAK, limit, cpt):
        if merged and tokens(segment, cpt) < minimum:
            merged[-1] += BREAK + segment
        else:
            merged.append(segment)
    if len(merged) > 1 and tokens(merged[0], cpt) < minimum:
        merged[:2] = [merged[0] + BREAK + merged[1]]
    return merged


# ---- tree -------------------------------------------------------------------------------

def subheading_of(text: str) -> str | None:
    first = next((line for line in text.splitlines() if line.strip()), "")
    if SECTION_OPENING.match(first) or not first.lstrip().startswith(("#", "■")):
        return None
    return HEADING_PREFIX.sub("", first).strip() or None


def link(rows: list[dict]) -> list[dict]:
    parents: dict[str, str | None] = {}
    concept: dict | None = None
    for row in rows:
        parent = None
        if row["kind"] == "section_text":
            concept = row
        elif row["kind"] == "example" and concept and (concept["section"], concept.get("part")) == (
                row["section"], row.get("part")):
            parent = concept["id"]
        parents[row["id"]] = parent
    children: dict[str, list[str]] = defaultdict(list)
    for chunk_id, parent in parents.items():
        if parent:
            children[parent].append(chunk_id)
    subheads = {r["id"]: subheading_of(r["text"]) for r in rows if r["kind"] == "section_text"}
    nodes = []
    for row in rows:
        label = row.get("label")
        if row["kind"] == "example" and not label:
            match = EXAMPLE_LABEL.match(row["text"])
            label = match.group(1) if match else None
        nodes.append({
            **row,
            "subheading": subheads.get(row["id"]) or subheads.get(parents[row["id"]] or ""),
            "example_label": f"Example {label}" if row["kind"] == "example" and label else None,
            "parent_id": parents[row["id"]],
            "child_ids": children.get(row["id"], []),
        })
    return nodes


def header(node: dict) -> str:
    location = " ".join(p for p in (node.get("section"), node.get("section_title")) if p)
    return " | ".join(p for p in (location, node.get("subheading"), node.get("example_label")) if p)


def build(rows: list[dict], kinds: set[str], limit: int, minimum: int, cpt: float):
    nodes, segments = [], []
    for node in link(rows):
        node_segments = []
        if node["kind"] in kinds:
            head = header(node)
            budget = limit - tokens(head + BREAK, cpt)
            if budget <= minimum:
                raise ValueError(f"{node['id']} 的標頭太長：{head}")
            texts = segment_text(node["text"], budget, minimum, cpt)
            for position, text in enumerate(texts, 1):
                embed = f"{head}{BREAK}{text}" if head else text
                node_segments.append({
                    "id": f"{node['id']}-s{position:02d}", "chunk_id": node["id"],
                    "parent_id": node["parent_id"], "kind": node["kind"],
                    "section": node.get("section"), "section_title": node.get("section_title"),
                    "subheading": node["subheading"], "example_label": node["example_label"],
                    "position": position, "segment_count": len(texts), "header": head,
                    "text": text, "embed_text": embed, "estimated_tokens": tokens(embed, cpt),
                })
        nodes.append({**node, "segment_ids": [s["id"] for s in node_segments]})
        segments += node_segments
    return nodes, segments


def write_jsonl(records: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent,
                                         prefix=f".{output.name}.", delete=False)
    try:
        with handle:
            handle.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        os.replace(handle.name, output)
    finally:
        Path(handle.name).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="建立父子關係並切成 embedding 片段")
    parser.add_argument("chunks", type=Path)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--min-tokens", type=int, default=MIN_TOKENS)
    parser.add_argument("--chars-per-token", type=float, default=CHARS_PER_TOKEN)
    parser.add_argument("--embed-kinds", nargs="+", default=["section_text", "sidebar"],
                        choices=["section_text", "sidebar", "example", "exercises"])
    parser.add_argument("--json", type=Path, help="同時把片段統計寫成 JSON")
    args = parser.parse_args()
    paths = {args.chunks.resolve(), args.tree.resolve(), args.segments.resolve()}
    if len(paths) != 3:
        parser.error("輸入與兩個輸出必須是不同檔案")
    if not 0 <= args.min_tokens < args.max_tokens:
        parser.error("需要 0 <= --min-tokens < --max-tokens")
    rows = [json.loads(line) for line in args.chunks.read_text(encoding="utf-8").splitlines() if line]
    try:
        nodes, segments = build(rows, set(args.embed_kinds), args.max_tokens, args.min_tokens,
                                args.chars_per_token)
    except ValueError as error:
        parser.error(str(error))
    write_jsonl(nodes, args.tree)
    write_jsonl(segments, args.segments)
    sizes = sorted(s["estimated_tokens"] for s in segments) or [0]
    over = sum(size > EMBED_LIMIT_TOKENS for size in sizes)
    linked = sum(1 for n in nodes if n["parent_id"])
    examples = sum(1 for n in nodes if n["kind"] == "example")
    segment_kinds = dict(Counter(s["kind"] for s in segments))
    print(f"{len(nodes)} 塊 → {len(segments)} 片段 {segment_kinds}")
    print(f"例題掛到子主題：{linked} / {examples}；片段 token 中位數 {sizes[len(sizes) // 2]}、"
          f"最大 {sizes[-1]}；超過 {EMBED_LIMIT_TOKENS}：{over}")
    write_report(args.json, "segments", ok=True, nodes=len(nodes), segments=len(segments),
                 segment_kinds=segment_kinds, examples=examples, linked_examples=linked,
                 token_median=sizes[len(sizes) // 2], token_max=sizes[-1],
                 embed_limit_tokens=EMBED_LIMIT_TOKENS, over_embed_limit=over,
                 max_tokens=args.max_tokens, chars_per_token=args.chars_per_token)


if __name__ == "__main__":
    main()
