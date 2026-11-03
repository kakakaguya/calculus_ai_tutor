"""Turn a Chinese question into an English search query for the English textbook.

nomic-embed-text is English-only: a Chinese question lands on unrelated sections
("連鎖律" matched 8.4 Economics instead of 2.5 The Chain Rule). The answer still uses
the original question; only the vector search sees the translation.

The model translates literally; it must not add a method the student did not mention
(it once turned "sin x / x 當 x 趨近 0" into "... using L'Hospital's Rule" and retrieval
went to 6.8 instead of 2.4) or the book's title. Terminology comes from the glossary.
"""

import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from tutor.glossary import Glossary


CJK = re.compile(r"[㐀-鿿]")
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
LABEL = re.compile(r"^(?:query|search query|english)\s*:\s*", re.IGNORECASE)
NO_TERMS = "(none)"
PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Translate the student's calculus question into English, to be used as a search query. "
     "Translate only what the student wrote. Do not add solution methods, theorem names, "
     "rule names or book titles that the student did not mention, and do not answer the "
     "question. Keep formulas and symbols as they are. "
     "Use these fixed translations for the terms that appear:\n{terms}\n"
     "Output only the English query on one line."),
    ("human", "{question}"),
])


def needs_translation(question: str) -> bool:
    return CJK.search(question) is not None


def clean_query(raw: str) -> str:
    text = THINK_BLOCK.sub("", raw)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return LABEL.sub("", first_line).strip().strip("\"'`")


class QueryTranslator:
    def __init__(self, llm: Runnable, glossary: Glossary | None = None) -> None:
        self._chain = PROMPT | llm | StrOutputParser()
        self._glossary = glossary or Glossary({})

    def __call__(self, question: str) -> str:
        if not needs_translation(question):
            return question
        matched = self._glossary.matches(question)
        terms = "\n".join(f"{chinese} = {english}" for chinese, english in matched) or NO_TERMS
        query = clean_query(self._chain.invoke({"question": question, "terms": terms}))
        english_terms = list(dict.fromkeys(english for _, english in matched))
        missing = [term for term in english_terms if term.casefold() not in query.casefold()]
        if not query:
            return " ".join(english_terms) or question
        return " ".join([query, *missing])
