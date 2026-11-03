"""Chinese → English calculus terms, kept in tutor/glossary.json so teachers can edit it.

Translation by a language model is not reliable for terminology: it may pick another
word than the textbook's, or add a method the student never mentioned. Terms found here
are handed to the translator and, if it still leaves them out, appended to the search
query, so a known term always reaches the vector search in the textbook's own words.
"""

import json
from pathlib import Path
import re


DEFAULT_GLOSSARY = Path(__file__).resolve().parent / "glossary.json"
SPACES = re.compile(r"\s+")


class Glossary:
    def __init__(self, terms: dict[str, str]) -> None:
        # Longest first, so "洛必達法則" is matched before "法則" could be.
        self._terms = sorted(((SPACES.sub("", chinese), english) for chinese, english in terms.items()),
                             key=lambda item: -len(item[0]))

    def matches(self, question: str) -> list[tuple[str, str]]:
        """(term, English) for each term in the question, in order, without overlaps."""
        text = SPACES.sub("", question)
        taken = [False] * len(text)
        found: list[tuple[int, str, str]] = []
        for term, english in self._terms:
            start = text.find(term)
            while start != -1:
                end = start + len(term)
                if not any(taken[start:end]):
                    taken[start:end] = [True] * len(term)
                    if all(term != seen for _, seen, _ in found):
                        found.append((start, term, english))
                start = text.find(term, end)
        return [(term, english) for _, term, english in sorted(found)]


def load_glossary(path: Path = DEFAULT_GLOSSARY) -> Glossary:
    """A missing file means no glossary; a malformed one is an error naming the file."""
    if not path.exists():
        return Glossary({})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} 不是合法的 JSON：{error.msg}") from error
    if not isinstance(data, dict) or not all(
            isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()
            for key, value in data.items()):
        raise ValueError(f"{path} 必須是 {{\"中文術語\": \"English term\"}} 格式，鍵和值都不能是空的")
    return Glossary(data)
