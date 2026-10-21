import json

from langchain_core.documents import Document
import pytest

from tutor.retrieval import (
    ContextBlock,
    Retriever,
    format_context,
    load_chunk_tree,
    select_context,
    source_list,
    wants_examples,
)


def _node(chunk_id: str, kind: str = "section_text", text: str = "Concept.", **extra) -> dict:
    node = {
        "id": chunk_id,
        "kind": kind,
        "section": "3.4",
        "section_title": "Limits at Infinity",
        "subheading": "Evaluating Limits",
        "example_label": None,
        "parent_id": None,
        "child_ids": [],
        "text": text,
    }
    return {**node, **extra}


def _hit(chunk_id: str, text: str = "Matched part.") -> Document:
    header = "3.4 Limits at Infinity | Evaluating Limits"
    return Document(
        page_content=f"{header}\n\n{text}",
        metadata={"chunk_id": chunk_id, "header": header, "section": "3.4",
                  "section_title": "Limits at Infinity"},
    )


TREE = {
    "A": _node("A", text="Concept A.", child_ids=["A1", "A2", "A3"]),
    "B": _node("B", text="Concept B.", subheading="Other Topic"),
    "C": _node("C", text="Concept C.", section="7.1", section_title="Integration by Parts"),
    "A1": _node("A1", "example", "EXAMPLE 1 First.", example_label="Example 1", parent_id="A"),
    "A2": _node("A2", "example", "EXAMPLE 2 Second.", example_label="Example 2", parent_id="A"),
    "A3": _node("A3", "example", "EXAMPLE 3 Third.", example_label="Example 3", parent_id="A"),
}


@pytest.mark.parametrize(
    "question",
    ["請舉例說明極限", "這題怎麼算？", r"計算 $\int_0^1 x^2 dx$", "如何求導數", "Evaluate the limit"],
)
def test_problem_questions_want_examples(question):
    assert wants_examples(question)


@pytest.mark.parametrize("question", ["什麼是極限？", "連續的定義是什麼", "為什麼導數代表斜率"])
def test_concept_questions_do_not_want_examples(question):
    assert not wants_examples(question)


def test_hits_are_deduplicated_into_whole_chunks_in_rank_order():
    hits = [_hit("A"), _hit("A"), _hit("B")]

    blocks = select_context(hits, TREE, include_examples=False)

    assert [block.chunk_id for block in blocks] == ["A", "B"]
    assert blocks[0].text == "Concept A."
    assert blocks[1].label == "3.4 Limits at Infinity | Other Topic"


def test_examples_follow_their_subtopic_only_when_wanted():
    blocks = select_context([_hit("A"), _hit("B")], TREE, include_examples=True, max_examples=2)

    assert [block.chunk_id for block in blocks] == ["A", "A1", "A2", "B"]
    assert blocks[1].is_example
    assert blocks[1].label.endswith("Example 1")


def test_chunk_limit_counts_subtopics_not_examples():
    blocks = select_context([_hit("A"), _hit("B")], TREE, include_examples=True, max_chunks=1)

    assert [block.chunk_id for block in blocks if not block.is_example] == ["A"]


def test_oversized_chunk_falls_back_to_the_matched_segment():
    tree = {**TREE, "A": _node("A", text="x" * 500, child_ids=["A1"])}

    blocks = select_context(
        [_hit("A", "Matched part.")], tree, include_examples=True,
        max_tokens=60, chars_per_token=1.0,
    )

    assert [block.chunk_id for block in blocks] == ["A", "A1"]
    assert blocks[0].text == "Matched part."


def test_examples_that_do_not_fit_are_left_out():
    blocks = select_context(
        [_hit("A")], TREE, include_examples=True, max_tokens=20, chars_per_token=1.0
    )

    assert [block.chunk_id for block in blocks] == ["A"]


def test_unknown_chunk_uses_the_hit_text():
    blocks = select_context([_hit("Z", "Orphan text.")], TREE, include_examples=False)

    assert blocks == (ContextBlock(
        chunk_id="Z", section="3.4", section_title="Limits at Infinity",
        label="3.4 Limits at Infinity | Evaluating Limits", text="Orphan text.", is_example=False,
    ),)


def test_blocks_carry_their_section():
    blocks = select_context([_hit("C")], TREE, include_examples=False)

    assert (blocks[0].section, blocks[0].section_title) == ("7.1", "Integration by Parts")


def _block(chunk_id: str, section: str, title: str, subheading: str, text: str) -> ContextBlock:
    return ContextBlock(chunk_id=chunk_id, section=section, section_title=title,
                        label=f"{section} {title} | {subheading}", text=text, is_example=False)


BLOCKS = (
    _block("A", "3.4", "Limits at Infinity", "Topic A", "Concept A."),
    _block("C", "7.1", "Integration by Parts", "Basics", "Concept C."),
    _block("B", "3.4", "Limits at Infinity", "Topic B", "Concept B."),
)


def test_format_context_numbers_blocks_by_section():
    assert format_context(BLOCKS) == (
        "【教材 1】3.4 Limits at Infinity | Topic A\nConcept A.\n\n"
        "【教材 2】7.1 Integration by Parts | Basics\nConcept C.\n\n"
        "【教材 1】3.4 Limits at Infinity | Topic B\nConcept B."
    )
    assert format_context(()) == "（沒有找到相關教材）"


def test_sources_list_each_section_once_with_the_context_numbers():
    assert source_list(BLOCKS) == (
        {"number": 1, "section": "3.4", "title": "Limits at Infinity",
         "label": "3.4 Limits at Infinity"},
        {"number": 2, "section": "7.1", "title": "Integration by Parts",
         "label": "7.1 Integration by Parts"},
    )


class FakeStore:
    def __init__(self, hits):
        self._hits = hits
        self.queries = []

    def similarity_search(self, query, k):
        self.queries.append((query, k))
        return self._hits


def test_retriever_gives_only_textbook_text_by_default():
    store = FakeStore([_hit("A")])
    retriever = Retriever(store, TREE, k=5)

    context = retriever.context("請舉例說明")

    assert store.queries == [("請舉例說明", 5)]
    assert "Concept A." in context
    assert "EXAMPLE 1" not in context


def test_retriever_can_attach_examples_when_enabled():
    retriever = Retriever(FakeStore([_hit("A")]), TREE, examples=True)

    assert any(block.is_example for block in retriever.retrieve("請舉例說明極限"))
    assert not any(block.is_example for block in retriever.retrieve("什麼是極限"))


def test_retriever_searches_with_the_rewritten_query():
    store = FakeStore([_hit("A")])
    retriever = Retriever(store, TREE, rewrite=lambda question: "limit")

    retriever.retrieve("什麼是極限")

    assert store.queries == [("limit", 8)]


def test_load_chunk_tree_indexes_by_id(tmp_path):
    path = tmp_path / "chunk_tree.jsonl"
    path.write_text("".join(json.dumps(node) + "\n" for node in TREE.values()), encoding="utf-8")

    assert load_chunk_tree(path)["A2"]["parent_id"] == "A"


def test_load_chunk_tree_explains_how_to_build_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_segments"):
        load_chunk_tree(tmp_path / "missing.jsonl")
