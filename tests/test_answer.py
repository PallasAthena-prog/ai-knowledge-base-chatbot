from app.answer import (
    PLACEHOLDER,
    _numbers,
    build_messages,
    clean_history,
    clean_rewrite,
    extractive_answer,
    finalize_answer,
    heuristic_query,
)
from app.search import Source
from app.textproc import split_sentences

CHUNK = (
    "Vacation allowance: full-time employees get 25 days of paid vacation per calendar year. "
    "You can carry up to 5 unused days into the next year. "
    "Carried days must be used by 31 March, after which they expire."
)
OFFSET = 500  # the chunk starts 500 characters into its page


def make_source(n=1, text=CHUNK, offset=OFFSET, title="Employee Handbook", page=3):
    sentences = [[s.start + offset, s.end + offset, int(s.heading)] for s in split_sentences(text)]
    return Source(
        n=n, chunk_id=n * 10, document_id=f"{n:032x}", title=title, file_type="pdf", page_no=page, page_count=7,
        heading="3. Paid time off", text=text, char_start=offset, char_end=offset + len(text), sentences=sentences,
        keyword_rank=1, semantic_rank=None, score=0.03,
    )


def test_markers_become_placeholders_and_point_at_the_supporting_sentence():
    source = make_source()
    answer = "You get 25 days of paid vacation a year [1]. Up to 5 unused days carry over [1]."
    markdown, citations = finalize_answer(answer, [source])
    assert markdown == f"You get 25 days of paid vacation a year{PLACEHOLDER.format(1)}. Up to 5 unused days carry over{PLACEHOLDER.format(2)}."
    first, second = citations
    s1, s2 = source.sentences[0], source.sentences[1]
    assert first["ranges"] == [[s1[0], s1[1]]]
    assert second["ranges"] == [[s2[0], s2[1]]]
    assert first["quotes"] == [CHUNK[: s1[1] - OFFSET]]
    assert first["label"] == "Employee Handbook, page 3"


def test_unknown_numbers_are_dropped_and_groups_are_split():
    a, b = make_source(1), make_source(2, title="Policy")
    markdown, citations = finalize_answer("Days expire on 31 March [1, 2]. Nonsense [9].", [a, b])
    assert [c["n"] for c in citations] == [1, 2]
    assert "[9]" not in markdown and "[1" not in markdown
    assert markdown.endswith(".") and "Nonsense." in markdown


def test_adjacent_markers_share_the_claim():
    a, b = make_source(1), make_source(2)
    _, citations = finalize_answer("Carried days must be used by 31 March [1][2].", [a, b])
    assert len(citations) == 2
    assert citations[0]["ranges"] == citations[1]["ranges"]


def test_citation_with_no_overlap_highlights_the_whole_passage():
    source = make_source()
    _, citations = finalize_answer("Totally unrelated words here [1].", [source])
    assert citations[0]["ranges"] == [[OFFSET, OFFSET + len(CHUNK)]]


def test_number_groups():
    assert _numbers("1-3") == [1, 2, 3]
    assert _numbers("1, 2 and 4") == [1, 2, 4]
    assert _numbers("2;2") == [2]


def test_extractive_answer_quotes_the_best_sentence():
    markdown, citations = extractive_answer("When do carried days expire?", [make_source()])
    assert "31 March" in markdown
    assert PLACEHOLDER.format(1) in markdown
    assert citations[0]["quotes"] == ["Carried days must be used by 31 March, after which they expire."]


def test_history_is_cleaned_and_prompt_contains_numbered_sources():
    history = [
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "How many days do I get?"},
        {"role": "assistant", "content": "You get 25 days [1]."},
    ]
    cleaned = clean_history(history)
    assert cleaned[0]["role"] == "user"
    assert cleaned[1]["content"] == "You get 25 days."
    messages = build_messages("And in the first year?", [make_source()], history, "Assistant", "Northwind")
    assert messages[0]["role"] == "system" and "Northwind" in messages[0]["content"]
    assert messages[-1]["content"].startswith("Sources:\n\n[1] Employee Handbook, page 3\n")
    assert messages[-1]["content"].endswith("Question: And in the first year?")


def test_query_rewrite_helpers():
    assert clean_rewrite('Rewritten question: "How many vacation days in the first year?"\n', "x") == (
        "How many vacation days in the first year?"
    )
    assert clean_rewrite("", "fallback") == "fallback"
    history = [{"role": "user", "content": "How many vacation days do I get?"}]
    assert heuristic_query("and abroad?", history) == "How many vacation days do I get? and abroad?"
    assert heuristic_query("What is the meal allowance when travelling abroad?", history).startswith("What is")


def test_brackets_in_code_are_not_citations():
    markdown, citations = finalize_answer("Use `items[1]` in the formula [1].\n```\nrow[1] = 2\n```", [make_source()])
    assert "`items[1]`" in markdown and "row[1] = 2" in markdown
    assert len(citations) == 1
