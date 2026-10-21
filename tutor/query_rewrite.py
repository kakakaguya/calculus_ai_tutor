"""Turn a Chinese question into an English search query for the English textbook.

nomic-embed-text is English-only: a Chinese question lands on unrelated sections
("連鎖律" matched 8.4 Economics instead of 2.5 The Chain Rule). The answer still uses
the original question; only the vector search sees the translation.
"""

import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable


CJK = re.compile(r"[㐀-鿿]")
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
LABEL = re.compile(r"^(?:query|search query|english)\s*:\s*", re.IGNORECASE)
PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Rewrite the student's calculus question as a short English search query for a "
     "calculus textbook (Stewart's Calculus). Use the textbook's terminology, e.g. "
     "連鎖律 → chain rule, 羅必達法則 → L'Hospital's Rule, 均值定理 → Mean Value Theorem. "
     "Keep any formulas. Output only the query on one line."),
    ("human", "{question}"),
])


def needs_translation(question: str) -> bool:
    return CJK.search(question) is not None


def clean_query(raw: str) -> str:
    text = THINK_BLOCK.sub("", raw)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return LABEL.sub("", first_line).strip().strip("\"'`")


class QueryTranslator:
    def __init__(self, llm: Runnable) -> None:
        self._chain = PROMPT | llm | StrOutputParser()

    def __call__(self, question: str) -> str:
        if not needs_translation(question):
            return question
        return clean_query(self._chain.invoke({"question": question})) or question
