"""Answer calculus questions with textbook context retrieved from Chroma.

Command line: python -m tutor.main_rag "什麼是極限？" [--show-context]
The index is opened on first use, so importing this module needs no running Ollama.
"""

import argparse
from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Protocol

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_ollama import ChatOllama

from tutor.query_rewrite import QueryTranslator
from tutor.retrieval import (
    NO_CONTEXT,
    ContextBlock,
    Retriever,
    format_context,
    load_chunk_tree,
    source_list,
)
from tutor.vector_store import CHROMA_DB_DIR, OLLAMA_BASE_URL, open_vector_store


OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
NUM_CTX = 8192  # Ollama's default window is smaller and would silently cut the context
TEMPERATURE = 0.1

SYSTEM_PROMPT = (
    "你是一位專業的微積分助教，請「絕對必須」全程使用繁體中文（zh-TW）作答，嚴禁出現簡體字。\n"
    "（請確保使用台灣數學名詞，例如將「函数」寫成「函數」，「导数」寫成「導數」，「变量」寫成「變數」）。\n"
    "正確理解使用者提供的 LaTeX，並保留其原意；不要破壞、刪除或任意改寫使用者提供的 LaTeX。\n"
    "回答中的數學式請使用 MathJax 支援的 LaTeX（行內以 \\( ... \\)，獨立公式以 \\[ ... \\] 表示）。\n"
    "解題時清楚列出使用的公式、代入步驟與最後答案。涉及定積分時，說明上下界與積分變數；涉及微分時，標示所使用的微分規則。\n"
    "若題目資訊不足，請明確指出缺少哪些條件，不可自行猜測。\n"
    "請務必「優先」使用以下提供的參考資料來回答問題。\n"
    "引用參考資料時，請在該句末尾標註【教材 n】的編號 n，例如［1］或［1］［2］。\n"
    "如果參考資料中無法回答該問題，請依靠你的專業知識補充，但要說明哪些部分來自教材。\n\n"
    "【參考資料】\n{context}"
)
PROMPT = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", "{input}")])


class BlockSource(Protocol):
    def retrieve(self, question: str) -> tuple[ContextBlock, ...]: ...


@dataclass(frozen=True)
class TutorAnswer:
    answer: str
    sources: tuple[dict, ...]


def _chain(llm: Runnable) -> Runnable:
    return PROMPT | llm | StrOutputParser()


def answer_with(question: str, retriever: BlockSource, llm: Runnable) -> TutorAnswer:
    blocks = retriever.retrieve(question)
    answer = _chain(llm).invoke({"context": format_context(blocks), "input": question})
    if not answer.strip():
        raise ValueError("沒有收到 AI 的回覆")
    return TutorAnswer(answer, source_list(blocks))


def format_sources(sources: tuple[dict, ...]) -> str:
    if not sources:
        return f"資料來源：{NO_CONTEXT}"
    lines = (f"［{source['number']}］{source['label']}" for source in sources)
    return "資料來源：\n" + "\n".join(lines)


def open_index():
    """Open Chroma, failing with a clear next step when it has not been built."""
    if not CHROMA_DB_DIR.exists():
        raise RuntimeError("向量資料庫不存在，請先執行 python -m ingestion.build_vector_db")
    store = open_vector_store()
    if not store.get(limit=1)["ids"]:
        raise RuntimeError("向量資料庫是空的，請先執行 python -m ingestion.build_vector_db")
    return store


@lru_cache(maxsize=1)
def _tutor() -> tuple[Retriever, ChatOllama]:
    # Translation is a one-line lookup, so thinking is turned off to keep it fast.
    translator = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL,
                            temperature=0, reasoning=False)
    retriever = Retriever(open_index(), load_chunk_tree(), rewrite=QueryTranslator(translator))
    llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL,
                     temperature=TEMPERATURE, num_ctx=NUM_CTX)
    return retriever, llm


def ask(question: str) -> TutorAnswer:
    retriever, llm = _tutor()
    return answer_with(question, retriever, llm)


def main() -> None:
    parser = argparse.ArgumentParser(description="微積分助教（命令列問答）")
    parser.add_argument("question", nargs="?",
                        default="請幫我解釋一下微積分中的極限概念，並舉一個簡單的例子來說明。")
    parser.add_argument("--show-context", action="store_true", help="先印出檢索到的教材")
    args = parser.parse_args()
    retriever, llm = _tutor()
    blocks = retriever.retrieve(args.question)
    context = format_context(blocks)
    if args.show_context:
        print(context, end="\n" + "=" * 50 + "\n")
    print(f"問題：{args.question}\n助教回答：", end="", flush=True)
    for piece in _chain(llm).stream({"context": context, "input": args.question}):
        print(piece, end="", flush=True)
    print("\n\n" + format_sources(source_list(blocks)))


if __name__ == "__main__":
    main()
