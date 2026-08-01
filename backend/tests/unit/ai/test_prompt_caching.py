"""Prompt caching is a byte-exact prefix match, and it fails silently.

A prompt that never caches costs the same as one that was never marked —
there is no error, just a bill. These tests pin the two things that make
the difference: volatile content stays behind the breakpoint, and the
breakpoints stay inside the API's 20-block lookback window.
"""

from src.ai.pricing import (
    CACHE_WRITE_MULTIPLIER,
    cost_without_cache,
    estimate_cost,
)
from src.ai.providers.anthropic_provider import (
    _LOOKBACK_BLOCKS,
    _MAX_MESSAGE_BREAKPOINTS,
    AnthropicProvider,
)
from src.ai.schemas import (
    ChatMessage,
    ChatRequest,
    ToolCall,
    ToolResult,
    Usage,
)

MODEL = "claude-opus-4-8"


def _request(**kwargs) -> ChatRequest:
    kwargs.setdefault("messages", [ChatMessage(role="user", content="hi")])
    kwargs.setdefault("model", MODEL)
    return ChatRequest(**kwargs)


def _cached(blocks) -> list[dict]:
    return [b for b in blocks if "cache_control" in b]


# --------------------------------------------------------------------------
# System prompt: the stable half is cached, the volatile half is not.
# --------------------------------------------------------------------------


def test_stable_system_is_cached_and_volatile_context_is_not():
    provider = AnthropicProvider()

    blocks = provider._system_payload(
        _request(system="persona rules", system_context="retrieved excerpts")
    )

    assert [b["text"] for b in blocks] == ["persona rules", "retrieved excerpts"]
    assert "cache_control" in blocks[0]
    # Marking this would write a fresh entry per request and read none.
    assert "cache_control" not in blocks[1]


def test_volatile_context_renders_after_the_breakpoint():
    provider = AnthropicProvider()

    blocks = provider._system_payload(
        _request(system="stable", system_context="volatile")
    )

    # Order is what makes caching possible: anything varying ahead of the
    # breakpoint invalidates the tools and system behind it.
    cached_index = blocks.index(_cached(blocks)[0])
    assert cached_index < len(blocks) - 1


def test_system_payload_is_omitted_when_there_is_no_system_prompt():
    provider = AnthropicProvider()

    payload = provider._system_payload(_request())

    assert not isinstance(payload, list)


def test_stable_only_prompt_still_caches():
    provider = AnthropicProvider()

    blocks = provider._system_payload(_request(system="persona rules"))

    assert len(blocks) == 1
    assert "cache_control" in blocks[0]


# --------------------------------------------------------------------------
# Conversation breakpoints.
# --------------------------------------------------------------------------


def _tool_round(index: int, tools_per_round: int) -> list[ChatMessage]:
    calls = [
        ToolCall(id=f"t{index}_{n}", name="get_cube", input={"n": n})
        for n in range(tools_per_round)
    ]

    return [
        ChatMessage(role="assistant", content=f"round {index}", tool_calls=calls),
        ChatMessage(
            role="user",
            tool_results=[
                ToolResult(tool_call_id=c.id, content="x" * 50, is_error=False)
                for c in calls
            ],
            content="",
        ),
    ]


def test_last_block_of_the_conversation_is_always_a_breakpoint():
    provider = AnthropicProvider()

    payload = provider._messages_payload(
        _request(messages=[ChatMessage(role="user", content="hello")])
    )

    assert payload[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_plain_string_content_is_promoted_to_a_block_so_it_can_be_marked():
    provider = AnthropicProvider()

    payload = provider._messages_payload(
        _request(messages=[ChatMessage(role="user", content="hello")])
    )

    assert payload[0]["content"] == [
        {
            "type": "text",
            "text": "hello",
            "cache_control": {"type": "ephemeral"},
        }
    ]


def test_long_tool_loop_gets_rolling_breakpoints_within_the_lookback_window():
    provider = AnthropicProvider()

    messages = [ChatMessage(role="user", content="start")]
    for index in range(5):
        messages.extend(_tool_round(index, tools_per_round=3))

    payload = provider._messages_payload(_request(messages=messages))

    positions = [
        offset
        for offset, (_message, block) in enumerate(
            (m, b)
            for m in payload
            for b in (
                m["content"] if isinstance(m["content"], list) else [m["content"]]
            )
        )
        if isinstance(block, dict) and "cache_control" in block
    ]

    assert len(positions) == _MAX_MESSAGE_BREAKPOINTS

    # Each breakpoint must be able to see the one before it, or it finds no
    # prior entry and silently misses.
    gaps = [b - a for a, b in zip(positions, positions[1:])]
    assert all(gap <= _LOOKBACK_BLOCKS + 1 for gap in gaps), gaps


def test_breakpoint_count_never_exceeds_the_api_budget():
    provider = AnthropicProvider()

    messages = [ChatMessage(role="user", content="start")]
    for index in range(15):
        messages.extend(_tool_round(index, tools_per_round=4))

    payload = provider._messages_payload(_request(messages=messages))

    marked = sum(
        1
        for message in payload
        for block in message["content"]
        if isinstance(block, dict) and "cache_control" in block
    )

    # Four total per request; the system block claims the fourth.
    assert marked == _MAX_MESSAGE_BREAKPOINTS


def test_short_conversation_gets_a_single_breakpoint():
    provider = AnthropicProvider()

    payload = provider._messages_payload(
        _request(
            messages=[
                ChatMessage(role="user", content="one"),
                ChatMessage(role="assistant", content="two"),
                ChatMessage(role="user", content="three"),
            ]
        )
    )

    marked = sum(
        1
        for message in payload
        for block in message["content"]
        if isinstance(block, dict) and "cache_control" in block
    )

    # Three blocks is well inside the lookback window — extra markers would
    # just pay the write premium for nothing.
    assert marked == 1


# --------------------------------------------------------------------------
# Tenant isolation.
# --------------------------------------------------------------------------


def test_cached_prefix_carries_no_tenant_identifiers():
    """Two organizations running the same agent share a cache prefix.

    That is the intended saving, and it is only safe because the cached
    half holds persona instructions and nothing else. Org-specific data
    (connection ids, retrieved documents) must stay in the volatile half,
    which is never cached and never shared.
    """

    provider = AnthropicProvider()

    org_a = provider._system_payload(
        _request(system="persona rules", system_context="org A connections")
    )
    org_b = provider._system_payload(
        _request(system="persona rules", system_context="org B connections")
    )

    assert org_a[0] == org_b[0]
    assert org_a[1] != org_b[1]
    assert "cache_control" not in org_a[1]
    assert "cache_control" not in org_b[1]


# --------------------------------------------------------------------------
# Cost accounting.
# --------------------------------------------------------------------------


def test_cache_reads_cost_a_tenth_of_ordinary_input():
    uncached = Usage(input_tokens=10_000, output_tokens=0)
    read = Usage(
        input_tokens=0, output_tokens=0, cache_read_input_tokens=10_000
    )

    assert estimate_cost(MODEL, read) * 10 == estimate_cost(MODEL, uncached)


def test_cache_writes_cost_a_premium_over_ordinary_input():
    uncached = Usage(input_tokens=10_000, output_tokens=0)
    write = Usage(
        input_tokens=0, output_tokens=0, cache_creation_input_tokens=10_000
    )

    assert estimate_cost(MODEL, write) == (
        estimate_cost(MODEL, uncached) * CACHE_WRITE_MULTIPLIER
    )


def test_a_cached_prefix_pays_for_itself_on_the_second_use():
    first = Usage(
        input_tokens=0, output_tokens=0, cache_creation_input_tokens=10_000
    )
    second = Usage(
        input_tokens=0, output_tokens=0, cache_read_input_tokens=10_000
    )
    twice_uncached = Usage(input_tokens=20_000, output_tokens=0)

    with_cache = estimate_cost(MODEL, first) + estimate_cost(MODEL, second)

    assert with_cache < estimate_cost(MODEL, twice_uncached)


def test_savings_is_the_gap_against_the_uncached_counterfactual():
    usage = Usage(
        input_tokens=1_000,
        output_tokens=500,
        cache_read_input_tokens=20_000,
    )

    actual = estimate_cost(MODEL, usage)
    counterfactual = cost_without_cache(MODEL, usage)

    assert counterfactual > actual
    # The whole saving comes from the read tier, not the output tokens.
    assert counterfactual - actual > 0


def test_cost_is_unchanged_for_providers_without_a_cache():
    usage = Usage(input_tokens=1_000, output_tokens=500)

    assert estimate_cost(MODEL, usage) == cost_without_cache(MODEL, usage)
