from app.llm import LLMError, ThinkFilter, error_for_status, parse_stream, strip_think


def test_parse_stream_reads_openai_style_events():
    lines = [
        ": keep-alive",
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        "",
        'data: {"choices":[{"delta":{"content":" world"},"finish_reason":null}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"ignored"}}]}',
    ]
    assert "".join(parse_stream(lines)) == "Hello world"


def test_parse_stream_raises_on_error_events():
    try:
        list(parse_stream(['data: {"error": {"message": "overloaded"}}']))
    except LLMError as exc:
        assert "overloaded" in str(exc)
    else:
        raise AssertionError("expected LLMError")


def test_think_blocks_are_removed_even_when_split_across_pieces():
    f = ThinkFilter()
    out = "".join(f.feed(p) for p in ["<thi", "nk>Let me reason", " about it.</th", "ink>\n\nYou get ", "25 days <", "b>"])
    out += f.flush()
    assert out == "You get 25 days <b>"


def test_plain_answers_pass_through():
    assert strip_think("No tags here.") == "No tags here."
    assert strip_think("<think>a</think>Answer") == "Answer"


def test_status_errors_have_friendly_messages():
    assert "API key" in error_for_status(401, "").user_message
    assert "LLM_MODEL" in error_for_status(404, "").user_message
    assert "rate limiting" in error_for_status(429, "").user_message
