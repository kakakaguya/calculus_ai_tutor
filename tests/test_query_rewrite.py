from langchain_core.runnables import RunnableLambda
import pytest

from tutor.glossary import Glossary
from tutor.query_rewrite import PROMPT, QueryTranslator, clean_query, needs_translation


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


GLOSSARY = Glossary({"連鎖律": "chain rule", "0除以0": "indeterminate form 0/0"})


def test_prompt_forbids_adding_methods_or_book_titles():
    system = PROMPT.messages[0].prompt.template

    assert "Do not add" in system
    assert "Stewart" not in system


def test_glossary_terms_are_given_to_the_model():
    prompts = []

    def fake_llm(prompt_value):
        prompts.append(prompt_value.to_string())
        return "How do you use the chain rule?"

    QueryTranslator(RunnableLambda(fake_llm), GLOSSARY)("連鎖律怎麼用？")

    assert "連鎖律 = chain rule" in prompts[0]


def test_glossary_term_the_model_left_out_is_appended():
    translate = QueryTranslator(RunnableLambda(lambda _: "What does 0 divided by 0 equal?"), GLOSSARY)

    assert translate("0 除以 0 等於多少") == "What does 0 divided by 0 equal? indeterminate form 0/0"


def test_glossary_term_already_in_the_query_is_not_repeated():
    translate = QueryTranslator(RunnableLambda(lambda _: "How do you use the Chain Rule?"), GLOSSARY)

    assert translate("連鎖律怎麼用？") == "How do you use the Chain Rule?"


def test_empty_output_falls_back_to_the_glossary_terms():
    assert QueryTranslator(RunnableLambda(lambda _: ""), GLOSSARY)("連鎖律怎麼用？") == "chain rule"
