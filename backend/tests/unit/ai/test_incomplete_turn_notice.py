"""A turn that ends abnormally must say so.

Only `tool_use` was ever inspected, so a turn ending in `max_tokens` or
`refusal` was rendered exactly like a completed one: a truncated answer
looked finished, and a refusal looked like an empty assistant message.
Both read as the product being broken rather than as something the user
can act on.

This matters more since adaptive thinking was enabled, because thinking
tokens and the visible answer now share the same max_tokens budget.
"""

from src.ai.orchestrator import _annotate_incomplete


def test_completed_turn_is_untouched():
    assert _annotate_incomplete("All done.", "end_turn") == "All done."


def test_tool_use_turn_is_untouched():
    assert _annotate_incomplete("Calling a tool.", "tool_use") == (
        "Calling a tool."
    )


def test_unknown_stop_reason_is_untouched():
    assert _annotate_incomplete("Text.", "something_new") == "Text."
    assert _annotate_incomplete("Text.", None) == "Text."


def test_truncated_turn_keeps_content_and_explains():
    result = _annotate_incomplete("The TI process reads the", "max_tokens")

    # The partial answer is still useful — it must be preserved, not
    # replaced by the notice.
    assert result.startswith("The TI process reads the")
    assert "cut off" in result
    assert "response size limit" in result


def test_refusal_explains_even_with_empty_content():
    """A refusal arrives with no content at all, which is exactly the
    case that previously rendered as a blank message."""

    result = _annotate_incomplete("", "refusal")

    assert result.strip() != ""
    assert "declined" in result


def test_notice_is_separated_from_the_answer():
    """Markdown needs a blank line or the notice joins the last
    sentence and reads as part of the model's answer."""

    result = _annotate_incomplete("Sentence.", "max_tokens")

    assert "\n\n_" in result
