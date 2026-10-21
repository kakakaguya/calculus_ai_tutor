from langchain_core.runnables import RunnableLambda
import pytest

from tutor import main_rag
from tutor.retrieval import ContextBlock


BLOCKS = (
    ContextBlock(chunk_id="A", section="6.8", section_title="L'Hospital's Rule",
                 label="6.8 L'Hospital's Rule | Topic", text="Concept A.", is_example=False),
    ContextBlock(chunk_id="B", section="3.4", section_title="Limits at Infinity",
                 label="3.4 Limits at Infinity", text="Concept B.", is_example=False),
)


class FakeRetriever:
    def __init__(self, blocks):
        self._blocks = blocks
        self.questions = []

    def retrieve(self, question: str):
        self.questions.append(question)
        return self._blocks


def test_answer_with_puts_numbered_context_into_the_prompt_and_returns_sources():
    seen = []

    def fake_llm(prompt_value):
        seen.append(prompt_value.to_messages())
        return "回答［1］"

    retriever = FakeRetriever(BLOCKS)

    result = main_rag.answer_with("羅必達法則？", retriever, RunnableLambda(fake_llm))

    assert result.answer == "回答［1］"
    assert [source["number"] for source in result.sources] == [1, 2]
    assert result.sources[1]["label"] == "3.4 Limits at Infinity"
    assert retriever.questions == ["羅必達法則？"]
    system, human = seen[0]
    assert "【教材 1】6.8 L'Hospital's Rule | Topic\nConcept A." in system.content
    assert "［1］" in system.content
    assert human.content == "羅必達法則？"


def test_prompt_keeps_the_latex_and_step_by_step_rules():
    for rule in ("不要破壞、刪除或任意改寫使用者提供的 LaTeX", "行內以 \\( ... \\)",
                 "清楚列出使用的公式、代入步驟與最後答案", "若題目資訊不足"):
        assert rule in main_rag.SYSTEM_PROMPT


def test_answer_without_context_has_no_sources():
    result = main_rag.answer_with("q", FakeRetriever(()), RunnableLambda(lambda _: "答"))

    assert result.sources == ()


def test_answer_with_rejects_an_empty_reply():
    with pytest.raises(ValueError, match="沒有收到"):
        main_rag.answer_with("q", FakeRetriever(BLOCKS), RunnableLambda(lambda _: "  "))


def test_format_sources_lists_one_line_per_source():
    assert main_rag.format_sources(main_rag.source_list(BLOCKS)) == (
        "資料來源：\n"
        "［1］6.8 L'Hospital's Rule\n"
        "［2］3.4 Limits at Infinity"
    )
    assert main_rag.format_sources(()) == "資料來源：（沒有找到相關教材）"


def test_open_index_explains_a_missing_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main_rag, "CHROMA_DB_DIR", tmp_path / "missing")

    with pytest.raises(RuntimeError, match="build_vector_db"):
        main_rag.open_index()


def test_open_index_explains_an_empty_collection(tmp_path, monkeypatch):
    class EmptyStore:
        def get(self, limit):
            return {"ids": []}

    monkeypatch.setattr(main_rag, "CHROMA_DB_DIR", tmp_path)
    monkeypatch.setattr(main_rag, "open_vector_store", lambda: EmptyStore())

    with pytest.raises(RuntimeError, match="是空的"):
        main_rag.open_index()
