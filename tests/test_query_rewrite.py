from langchain_core.runnables import RunnableLambda
import pytest

from tutor.query_rewrite import QueryTranslator, clean_query, needs_translation


@pytest.mark.parametrize(
    ("question", "expected"),
    [("什麼是極限？", True), ("連鎖律 chain rule", True), ("What is a limit?", False),
     (r"$\int_0^1 x^2 dx$", False)],
)
def test_needs_translation_detects_chinese(question, expected):
    assert needs_translation(question) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("chain rule derivative", "chain rule derivative"),
        ('"chain rule"\n', "chain rule"),
        ("<think>\nlet me think\n</think>\n\nchain rule", "chain rule"),
        ("Query: horizontal asymptote", "horizontal asymptote"),
        ("integration by parts\nExplanation: ...", "integration by parts"),
    ],
)
def test_clean_query_keeps_only_the_query_line(raw, expected):
    assert clean_query(raw) == expected


def test_translator_rewrites_chinese_questions():
    prompts = []

    def fake_llm(prompt_value):
        prompts.append(prompt_value.to_string())
        return "chain rule"

    translate = QueryTranslator(RunnableLambda(fake_llm))

    assert translate("連鎖律怎麼用？") == "chain rule"
    assert "連鎖律怎麼用？" in prompts[0]


def test_translator_leaves_english_untouched_without_calling_the_model():
    def fail(_):
        raise AssertionError("should not be called")

    assert QueryTranslator(RunnableLambda(fail))("What is a limit?") == "What is a limit?"


def test_translator_falls_back_to_the_question_on_empty_output():
    assert QueryTranslator(RunnableLambda(lambda _: "  "))("什麼是極限？") == "什麼是極限？"
