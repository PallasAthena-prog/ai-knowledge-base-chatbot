from app.chunking import chunk_pages

PAGE_ONE = (
    "3. Paid time off\n"
    "Vacation allowance: full-time employees get 25 days of paid vacation per calendar year, plus UK\n"
    "bank holidays. Part-time allowances are calculated pro rata.\n"
    "Your first year: if you join during the year, your allowance for that year is prorated by the number\n"
    "of full months you work. During the first three months you can take up to 5 of those days.\n"
    "Carrying days over: you can carry up to 5 unused days into the next year. Carried days must be used by\n"
    "31 March, after which they expire.\n"
    "4. Sick leave\n"
    "If you are ill, tell your manager before 10:00 on the first day. You can self-certify for up to 7 days."
)
PAGE_TWO = "Northwind pays full salary for up to 15 working days of sick leave. After that, statutory pay applies."


def test_chunks_map_exactly_onto_page_text():
    pages = [PAGE_ONE, PAGE_TWO]
    chunks = chunk_pages(pages, chunk_size=300, overlap=80)
    assert len(chunks) >= 3
    for chunk in chunks:
        page = pages[chunk.page_no - 1]
        assert page[chunk.start:chunk.end] == chunk.text
        assert len(chunk.text) <= 300 + 80
        for start, end, _ in chunk.sentences:
            assert chunk.start <= start < end <= chunk.end
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_chunks_never_cross_pages_and_headings_carry_over():
    chunks = chunk_pages([PAGE_ONE, PAGE_TWO], chunk_size=300, overlap=80)
    last = chunks[-1]
    assert last.page_no == 2
    assert last.heading == "4. Sick leave"
    assert chunks[0].heading == "3. Paid time off"


def test_overlap_repeats_the_last_sentence():
    chunks = [c for c in chunk_pages([PAGE_ONE], chunk_size=300, overlap=150) if c.page_no == 1]
    shared = [a for a, b in zip(chunks, chunks[1:]) if b.start < a.end]
    assert shared, "expected at least one pair of overlapping chunks"


def test_new_section_starts_a_new_chunk():
    page = (
        "# Remote work\n\nYou may work abroad for 20 days. Ask first.\n\n"
        "# Expenses\n\nMeals are covered up to 40 pounds per day."
    )
    chunks = chunk_pages([page], chunk_size=60, overlap=0)
    assert [c.heading for c in chunks] == ["Remote work", "Expenses"]
    assert chunks[1].text.startswith("# Expenses")


def test_empty_pages_give_no_chunks():
    assert chunk_pages(["", "   "]) == []
