"""Find the textbook text for a question: match segments, return whole subtopics.

Only section_text is embedded. A hit is expanded to its full chunk from
chunk_tree.jsonl, within a context token budget. Answers rely on textbook text alone;
attaching the examples under a subtopic (child_ids) is kept as an option, off by default.
Context and sources are numbered per book section, so ［1］ in an answer names a section.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Callable, Protocol

from langchain_core.documents import Document

from ingestion.segment_text import CHARS_PER_TOKEN, estimate_tokens


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNK_TREE = PROJECT_ROOT / "data" / "chunk_tree.jsonl"
SEARCH_K = 8  # segments per query; several often belong to the same subtopic
MAX_CHUNKS = 3
MAX_EXAMPLES = 2
MAX_CONTEXT_TOKENS = 5000  # leaves room for the question and answer within NUM_CTX
LABEL_SEPARATOR = " | "
NO_CONTEXT = "（沒有找到相關教材）"
EXAMPLE_REQUEST = re.compile(
    r"例題|例子|舉例|範例|示範|練習|解題|計算|求解|怎麼(?:算|做|解|求)|如何(?:算|求|解)"
    r"|\b(?:example|evaluate|compute|calculate|solve|find)\b"
    r"|\$|\\(?:int|lim|frac|sum|sqrt)|[∫∑√]",
    re.IGNORECASE,
)


class SimilaritySearch(Protocol):
    def similarity_search(self, query: str, k: int) -> list[Document]: ...


@dataclass(frozen=True)
class ContextBlock:
    chunk_id: str
    section: str | None
    section_title: str | None
    label: str
    text: str
    is_example: bool

    @property
    def section_name(self) -> str:
        return " ".join(part for part in (self.section, self.section_title) if part)


def load_chunk_tree(path: Path = DEFAULT_CHUNK_TREE) -> dict[str, dict]:
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}，請先執行 python -m ingestion.build_segments")
    nodes = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    return {node["id"]: node for node in nodes}


def wants_examples(question: str) -> bool:
    """Problem-solving questions get worked examples; definition questions do not."""
    return EXAMPLE_REQUEST.search(question) is not None


def _label(node: dict) -> str:
    location = " ".join(part for part in (node.get("section"), node.get("section_title")) if part)
    return LABEL_SEPARATOR.join(
        part for part in (location, node.get("subheading"), node.get("example_label")) if part
    )


def _hit_text(hit: Document) -> str:
    header = hit.metadata.get("header", "")
    return hit.page_content.removeprefix(f"{header}\n\n") if header else hit.page_content


def _concept_blocks(
    hits: list[Document], tree: dict[str, dict], max_chunks: int, budget: int, cpt: float
) -> list[ContextBlock]:
    blocks: list[ContextBlock] = []
    used = 0
    for hit in hits:
        chunk_id = hit.metadata["chunk_id"]
        if len(blocks) >= max_chunks or any(block.chunk_id == chunk_id for block in blocks):
            continue
        node = tree.get(chunk_id)
        source = node or hit.metadata
        label = _label(node) if node else hit.metadata.get("header", "")
        text = node["text"] if node else _hit_text(hit)
        if used + estimate_tokens(text, cpt) > budget:
            text = _hit_text(hit)  # the whole subtopic is too long: keep the matched part
        if used + estimate_tokens(text, cpt) > budget:
            continue
        blocks.append(ContextBlock(chunk_id, source.get("section"), source.get("section_title"),
                                   label, text, False))
        used += estimate_tokens(text, cpt)
    return blocks


def select_context(
    hits: list[Document],
    tree: dict[str, dict],
    include_examples: bool,
    max_chunks: int = MAX_CHUNKS,
    max_examples: int = MAX_EXAMPLES,
    max_tokens: int = MAX_CONTEXT_TOKENS,
    chars_per_token: float = CHARS_PER_TOKEN,
) -> tuple[ContextBlock, ...]:
    """Unique subtopics in rank order, each followed by its examples when wanted."""
    concepts = _concept_blocks(hits, tree, max_chunks, max_tokens, chars_per_token)
    if not include_examples:
        return tuple(concepts)
    used = sum(estimate_tokens(block.text, chars_per_token) for block in concepts)
    examples_left = max_examples
    ordered: list[ContextBlock] = []
    for concept in concepts:
        ordered.append(concept)
        for child_id in tree.get(concept.chunk_id, {}).get("child_ids", []):
            child = tree.get(child_id)
            if examples_left == 0 or child is None:
                break
            cost = estimate_tokens(child["text"], chars_per_token)
            if used + cost > max_tokens:
                continue
            ordered.append(ContextBlock(child_id, child.get("section"), child.get("section_title"),
                                        _label(child), child["text"], True))
            used += cost
            examples_left -= 1
    return tuple(ordered)


def _block_type(block: ContextBlock) -> str:
    return "例題" if block.is_example else "教材"


def _section_numbers(blocks: tuple[ContextBlock, ...]) -> dict[str, int]:
    """1, 2, ... per distinct section, in the order the sections first appear."""
    numbers: dict[str, int] = {}
    for block in blocks:
        numbers.setdefault(block.section_name, len(numbers) + 1)
    return numbers


def format_context(blocks: tuple[ContextBlock, ...]) -> str:
    """Numbered by section so ［n］ in the answer matches the sources list."""
    if not blocks:
        return NO_CONTEXT
    numbers = _section_numbers(blocks)
    return "\n\n".join(
        f"【{_block_type(block)} {numbers[block.section_name]}】{block.label}\n{block.text}"
        for block in blocks
    )


def source_list(blocks: tuple[ContextBlock, ...]) -> tuple[dict, ...]:
    """Each book section once, e.g. ［1］7.1 Integration by Parts."""
    first_blocks = {block.section_name: block for block in reversed(blocks)}
    return tuple(
        {"number": number, "section": first_blocks[name].section,
         "title": first_blocks[name].section_title, "label": name}
        for name, number in _section_numbers(blocks).items()
    )


class Retriever:
    def __init__(
        self,
        store: SimilaritySearch,
        tree: dict[str, dict],
        k: int = SEARCH_K,
        rewrite: Callable[[str], str] = lambda question: question,
        examples: bool = False,
    ) -> None:
        self._store = store
        self._tree = tree
        self._k = k
        self._rewrite = rewrite
        self._examples = examples

    def retrieve(self, question: str) -> tuple[ContextBlock, ...]:
        """Search with the rewritten query; decide on examples from the original wording."""
        hits = self._store.similarity_search(self._rewrite(question), k=self._k)
        include_examples = self._examples and wants_examples(question)
        return select_context(hits, self._tree, include_examples)

    def context(self, question: str) -> str:
        return format_context(self.retrieve(question))
