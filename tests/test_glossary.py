import json

import pytest

from tutor.glossary import DEFAULT_GLOSSARY, Glossary, load_glossary


def test_longest_term_wins_and_terms_do_not_overlap():
    glossary = Glossary({"洛必達法則": "L'Hospital's Rule", "法則": "rule"})

    assert glossary.matches("洛必達法則怎麼用？") == [("洛必達法則", "L'Hospital's Rule")]


def test_matching_ignores_spaces():
    glossary = Glossary({"0除以0": "indeterminate form 0/0"})

    assert glossary.matches("0 除以 0 等於多少") == [("0除以0", "indeterminate form 0/0")]


def test_terms_are_returned_in_question_order():
    glossary = Glossary({"均值定理": "Mean Value Theorem", "連鎖律": "chain rule"})

    assert [en for _, en in glossary.matches("連鎖律和均值定理有關嗎")] == [
        "chain rule", "Mean Value Theorem"]


def test_a_term_is_reported_once_even_if_repeated():
    glossary = Glossary({"極限": "limit"})

    assert glossary.matches("極限的極限") == [("極限", "limit")]


def test_missing_file_gives_an_empty_glossary(tmp_path):
    assert load_glossary(tmp_path / "missing.json").matches("連鎖律") == []


@pytest.mark.parametrize("content", ["{not json", '["a", "b"]', '{"連鎖律": 3}', '{"": "x"}'])
def test_invalid_file_is_rejected_with_its_path(tmp_path, content):
    path = tmp_path / "glossary.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="glossary.json"):
        load_glossary(path)


def test_shipped_glossary_covers_the_known_terminology_problems():
    glossary = load_glossary(DEFAULT_GLOSSARY)

    def english(question: str) -> list[str]:
        return [en for _, en in glossary.matches(question)]

    assert "L'Hospital's Rule" in english("洛必達法則")
    assert "L'Hospital's Rule" in english("羅必達法則")
    assert "chain rule" in english("連鎖律怎麼用？")
    assert "improper integral" in english("瑕積分")
    assert any("indeterminate" in en for en in english("0 除以 0 等於多少"))
    assert json.loads(DEFAULT_GLOSSARY.read_text(encoding="utf-8"))
