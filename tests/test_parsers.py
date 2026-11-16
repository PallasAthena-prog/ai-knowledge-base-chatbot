from app.parsers import ParseError, parse_file, strip_repeated_lines, title_from_filename
from support import FAQ, POLICY


def test_word_document_keeps_headings_lists_and_tables():
    parsed = parse_file(POLICY, POLICY.name)
    assert parsed.file_type == "docx"
    assert parsed.title == "Northwind Analytics IT Security Policy"
    text = parsed.pages[0]
    assert "# 4. Lost or stolen devices" in text
    assert "- Do not try to track down or recover a stolen device yourself." in text
    assert "Confidential | Customer data, contracts, salaries | Named people only, never on personal devices" in text


def test_markdown_title_comes_from_the_first_heading():
    parsed = parse_file(FAQ, FAQ.name)
    assert parsed.file_type == "md"
    assert parsed.title == "Northwind Analytics Product FAQ"
    assert len(parsed.pages) == 1


def test_running_headers_and_footers_are_removed():
    bodies = ["Working hours are flexible.", "Vacation is 25 days.", "Expenses are paid monthly.", "Laptops last three years."]
    pages = [f"{body}\nAsk the People team.\nAcme handbook | Page {n} of 4" for n, body in enumerate(bodies, 1)]
    cleaned = strip_repeated_lines(pages)
    assert all("Acme handbook" not in page for page in cleaned)
    assert cleaned[1] == "Vacation is 25 days."


def test_unsupported_and_broken_files(tmp_path):
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip file")
    for path, name in ((broken, "broken.docx"), (broken, "picture.png")):
        try:
            parse_file(path, name)
        except ParseError:
            continue
        raise AssertionError(f"{name} should not parse")


def test_title_from_filename():
    assert title_from_filename("team_offsite-plan 2026.pdf") == "team offsite plan 2026"
