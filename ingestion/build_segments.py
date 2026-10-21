"""data/chunks.jsonl → chunk tree (full chunks for answers) + segments (for embedding).

Every chunk stays whole in chunk_tree.jsonl, with parent_id/child_ids linking examples to
their subtopic. Only section_text is embedded by default: retrieval matches a concept and
its examples come along through child_ids. segments.jsonl splits only chunks longer than
--max-tokens; each segment points back to its chunk, so a match returns the whole chunk.

Run from the project root: python -m ingestion.build_segments
"""

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, replace
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Iterable

from ingestion.chunk_tree import ChunkNode, link_chunks
from ingestion.segment_text import CHARS_PER_TOKEN, estimate_tokens, segment_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "chunks.jsonl"
DEFAULT_TREE_OUTPUT = PROJECT_ROOT / "data" / "chunk_tree.jsonl"
DEFAULT_SEGMENTS_OUTPUT = PROJECT_ROOT / "data" / "segments.jsonl"
MAX_TOKENS = 500
MIN_TOKENS = 100
EMBED_CONTEXT_TOKENS = 2048  # nomic-embed-text truncates beyond this
CHUNK_KINDS = ("section_text", "example", "exercises")
DEFAULT_EMBED_KINDS = frozenset({"section_text"})
HEADER_SEPARATOR = " | "
REQUIRED_FIELDS = (
    "id", "index", "kind", "part", "section", "section_title", "text",
    "source_files", "source_spans",
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Segment:
    id: str
    chunk_id: str
    parent_id: str | None
    kind: str
    part: str
    section: str | None
    section_title: str | None
    subheading: str | None
    example_label: str | None
    position: int
    segment_count: int
    header: str
    text: str
    embed_text: str
    estimated_tokens: int


def load_chunks(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} 第 {line_number} 行不是合法 JSON：{error.msg}") from error
        if not isinstance(row, dict):
            raise ValueError(f"{path} 第 {line_number} 行不是 JSON 物件")
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        if missing:
            raise ValueError(f"{path} 第 {line_number} 行缺少欄位：{', '.join(missing)}")
        rows.append(row)
    return rows


def segment_header(node: ChunkNode) -> str:
    """Where the text sits in the book, prepended so short segments keep their context."""
    location = " ".join(part for part in (node.section, node.section_title) if part)
    return HEADER_SEPARATOR.join(
        part for part in (location, node.subheading, node.example_label) if part
    )


def _segments_for(
    node: ChunkNode, max_tokens: int, min_tokens: int, chars_per_token: float
) -> tuple[Segment, ...]:
    header = segment_header(node)
    prefix = f"{header}\n\n" if header else ""
    budget = max_tokens - estimate_tokens(prefix, chars_per_token)
    if budget <= min_tokens:
        raise ValueError(f"{node.id} 的標頭太長，剩下 {budget} token 不足以放內容：{header}")
    texts = segment_text(node.text, budget, min_tokens, chars_per_token)
    segments = []
    for position, text in enumerate(texts, 1):
        embed_text = prefix + text
        segments.append(Segment(
            id=f"{node.id}-s{position:02d}",
            chunk_id=node.id,
            parent_id=node.parent_id,
            kind=node.kind,
            part=node.part,
            section=node.section,
            section_title=node.section_title,
            subheading=node.subheading,
            example_label=node.example_label,
            position=position,
            segment_count=len(texts),
            header=header,
            text=text,
            embed_text=embed_text,
            estimated_tokens=estimate_tokens(embed_text, chars_per_token),
        ))
    return tuple(segments)


def build_outputs(
    rows: list[dict],
    max_tokens: int = MAX_TOKENS,
    min_tokens: int = MIN_TOKENS,
    chars_per_token: float = CHARS_PER_TOKEN,
    embed_kinds: frozenset[str] = DEFAULT_EMBED_KINDS,
) -> tuple[tuple[ChunkNode, ...], tuple[Segment, ...]]:
    nodes: list[ChunkNode] = []
    segments: list[Segment] = []
    for node in link_chunks(rows):
        if node.kind not in embed_kinds:
            nodes.append(node)
            continue
        node_segments = _segments_for(node, max_tokens, min_tokens, chars_per_token)
        nodes.append(replace(node, segment_ids=tuple(segment.id for segment in node_segments)))
        segments.extend(node_segments)
    for segment in segments:
        if segment.estimated_tokens > EMBED_CONTEXT_TOKENS:
            logger.warning("%s 約 %s token，超過 embedding 上限 %s，尾端會被截斷",
                           segment.id, segment.estimated_tokens, EMBED_CONTEXT_TOKENS)
    return tuple(nodes), tuple(segments)


def write_jsonl(records: Iterable[dict], output_path: Path) -> None:
    """Write atomically so an interrupted run never leaves a half-written file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_path.parent,
            prefix=f".{output_path.name}.", suffix=".tmp", delete=False,
        ) as output_file:
            temporary_path = Path(output_file.name)
            for record in records:
                output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _log_summary(nodes: tuple[ChunkNode, ...], segments: tuple[Segment, ...]) -> None:
    split = sum(1 for node in nodes if len(node.segment_ids) > 1)
    linked = sum(1 for node in nodes if node.parent_id is not None)
    by_kind = Counter(segment.kind for segment in segments)
    logger.info("%s 個文字塊 → %s 個片段（%s 塊被切開；%s 個例題掛到子主題）",
                len(nodes), len(segments), split, linked)
    logger.info("片段種類：%s", "、".join(f"{kind} {count}" for kind, count in by_kind.items()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="建立文字塊父子關係並切成 embedding 片段")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--tree-output", type=Path, default=DEFAULT_TREE_OUTPUT)
    parser.add_argument("--segments-output", type=Path, default=DEFAULT_SEGMENTS_OUTPUT)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                        help="每個片段的 token 上限（含標頭）")
    parser.add_argument("--min-tokens", type=int, default=MIN_TOKENS,
                        help="小於此值的片段併入相鄰片段")
    parser.add_argument("--chars-per-token", type=float, default=CHARS_PER_TOKEN,
                        help="估算 token 用；換 embedding 模型時要重新量")
    parser.add_argument("--embed-kinds", nargs="+", choices=CHUNK_KINDS,
                        default=sorted(DEFAULT_EMBED_KINDS),
                        help="要切成片段做 embedding 的種類；預設只有 section_text")
    args = parser.parse_args(argv)

    paths = [args.input.resolve(), args.tree_output.resolve(), args.segments_output.resolve()]
    if len(set(paths)) != len(paths):
        parser.error("輸入與兩個輸出必須是不同的檔案")

    try:
        rows = load_chunks(args.input)
        nodes, segments = build_outputs(rows, args.max_tokens, args.min_tokens,
                                        args.chars_per_token, frozenset(args.embed_kinds))
        write_jsonl((asdict(node) for node in nodes), args.tree_output)
        write_jsonl((asdict(segment) for segment in segments), args.segments_output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    _log_summary(nodes, segments)
    logger.info("已輸出 %s 與 %s", args.tree_output, args.segments_output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
