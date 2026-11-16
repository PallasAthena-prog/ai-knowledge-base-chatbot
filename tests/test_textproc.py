from app.textproc import content_terms, normalize_text, split_sentences, stem


def texts(text):
    return [text[s.start:s.end] for s in split_sentences(text)]


def test_sentences_respect_abbreviations():
    text = "Bring a laptop, e.g. a MacBook. Ask Dr. Smith first. Then go home."
    assert texts(text) == ["Bring a laptop, e.g. a MacBook.", "Ask Dr. Smith first.", "Then go home."]


def test_headings_and_bullets_become_their_own_spans():
    text = "3. Paid time off\nYou get 25 days. Plan ahead.\n- First item\n- Second item"
    spans = split_sentences(text)
    assert spans[0].heading
    assert text[spans[0].start:spans[0].end] == "3. Paid time off"
    assert texts(text)[1:] == ["You get 25 days.", "Plan ahead.", "- First item", "- Second item"]
    assert not any(s.heading for s in spans[1:])


def test_wrapped_lines_are_not_mistaken_for_headings():
    text = "Stays longer than 20 working days need approval from the\nPeople team, as they can affect tax."
    spans = split_sentences(text)
    assert len(spans) == 1
    assert not spans[0].heading


def test_markdown_headings_are_detected():
    spans = split_sentences("## Is there a free trial?\n\nYes. Every account starts with a trial.")
    assert spans[0].heading
    assert len(spans) == 3


def test_sentence_offsets_point_into_the_original_text():
    text = "First line of a paragraph\nthat wraps. Second sentence here!\n\nNew paragraph."
    for span in split_sentences(text):
        assert text[span.start:span.end].strip() == text[span.start:span.end]
        assert span.end > span.start


def test_normalize_joins_words_broken_across_lines():
    assert normalize_text("employ-\nment  rules\r\n\n\n\nnext") == "employment rules\n\nnext"


def test_content_terms_and_stem():
    assert content_terms("How many vacation days do I get?") == ["many", "vacation", "days"]
    assert stem("days") == "day"
    assert stem("policies") == "policy"
    assert stem("reported") == "report"
