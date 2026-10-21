from ingestion.segment_text import estimate_tokens, segment_text


def _segment(text: str, max_tokens: int, min_tokens: int = 1) -> tuple[str, ...]:
    # One character per token keeps the expected boundaries easy to read.
    return segment_text(text, max_tokens=max_tokens, min_tokens=min_tokens, chars_per_token=1.0)


def test_estimate_tokens_rounds_up():
    assert estimate_tokens("abcdefg", chars_per_token=3.0) == 3
    assert estimate_tokens("", chars_per_token=3.0) == 0


def test_short_text_is_a_single_segment():
    assert _segment("Only one paragraph.", max_tokens=100) == ("Only one paragraph.",)


def test_paragraphs_are_packed_without_exceeding_the_limit_or_losing_text():
    paragraphs = [chr(ord("a") + number) * 40 for number in range(5)]
    text = "\n\n".join(paragraphs)

    segments = _segment(text, max_tokens=100, min_tokens=20)

    assert segments == (
        "\n\n".join(paragraphs[0:2]),
        "\n\n".join(paragraphs[2:4]),
        paragraphs[4],
    )
    assert all(len(segment) <= 100 for segment in segments)
    assert "\n\n".join(segments) == text


def test_display_math_stays_with_its_lead_in_and_continuation():
    intro = "Intro paragraph that fills most of the first segment."
    formula = "We write\n\n$$\n\\lim_{x \\to a} f(x) = L\n$$\n\nwhere $L$ is the limit."
    text = f"{intro}\n\n{formula}"

    segments = _segment(text, max_tokens=80)

    assert segments == (intro, formula)


def test_display_math_larger_than_the_limit_is_never_split():
    formula = "$$\n" + " + ".join(f"x_{{{n}}}" for n in range(40)) + "\n$$"
    text = f"Sum of terms:\n\n{formula}"

    segments = _segment(text, max_tokens=50)

    assert any(formula in segment for segment in segments)


def test_short_tail_is_merged_into_the_previous_segment():
    head = "h" * 90
    tail = "t" * 15

    assert _segment(f"{head}\n\n{tail}", max_tokens=100, min_tokens=30) == (f"{head}\n\n{tail}",)


def test_heading_paragraph_starts_the_segment_it_introduces():
    first = "a" * 60
    second = "b" * 60

    segments = _segment(f"{first}\n\n## Sub\n\n{second}", max_tokens=100)

    assert segments == (first, f"## Sub\n\n{second}")


def test_oversized_paragraph_splits_at_sentences_outside_inline_math():
    first = "Alpha has $a. B$ inside."
    second = "Beta sentence."
    third = "Gamma sentence."

    segments = _segment(f"{first} {second} {third}", max_tokens=40, min_tokens=5)

    assert segments == (f"{first} {second}", third)


def test_escaped_dollar_is_currency_not_math():
    first = r"It costs \$9 per meter."
    second = "When $x = 1000$ it grows."

    segments = _segment(f"{first} {second}", max_tokens=30, min_tokens=5)

    assert segments == (first, second)
