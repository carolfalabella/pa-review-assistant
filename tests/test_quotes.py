"""Quote verification: the check that catches fabricated citations."""

from src.ingest import read_pages
from src.verify import check_citation, normalize, quote_on_page

from .conftest import DATA

PAGES = {p.number: p.text for p in read_pages(DATA / "case_001.pdf")}


def test_exact_quote_passes():
    assert quote_on_page("Radicular symptoms in the right lower extremity persist", PAGES[7])[0]


def test_quotation_marks_whitespace_and_case_are_forgiven():
    # Qwen wrapped every quote in quotation marks during the benchmark.
    assert quote_on_page('“RADICULAR symptoms   in the right\nlower extremity persist.”', PAGES[7])[0]


def test_quote_across_a_pdf_line_wrap_passes():
    # On page 3 this sentence wraps after "the pain" in the extracted text.
    assert quote_on_page("Since early August 2026 the pain radiates from the right buttock", PAGES[3])[0]


def test_paraphrase_fails():
    ok, reason = quote_on_page("Patient had a lumbar MRI in June 2026", PAGES[3])
    assert not ok and "not found" in reason


def test_one_changed_word_fails():
    assert not quote_on_page("Radicular symptoms in the left lower extremity persist", PAGES[7])[0]


def test_real_quote_on_wrong_page_fails():
    assert not check_citation(3, "Radicular symptoms in the right lower extremity persist", PAGES)["verified"]


def test_page_that_does_not_exist_fails():
    c = check_citation(12, "Radicular symptoms in the right lower extremity persist", PAGES)
    assert not c["verified"] and "does not exist" in c["check"]


def test_too_short_quote_fails():
    assert not quote_on_page("PT", PAGES[6])[0]


def test_ellipsis_stitched_quote_fails():
    assert not quote_on_page("The patient demonstrated ... over the episode of care", PAGES[7])[0]


def test_normalize_unifies_dashes():
    assert normalize("L4–L5") == normalize("L4-L5")


def test_locate_quote_finds_original_span_across_a_line_wrap():
    from src.verify import locate_quote
    text = PAGES[3]
    quote = "“Since early August 2026 the pain radiates from the right buttock.”"
    start, end = locate_quote(text, quote)
    assert text[start:end].replace("\n", " ") == "Since early August 2026 the pain radiates from the right buttock"


def test_locate_quote_returns_none_for_a_fabricated_quote():
    from src.verify import locate_quote
    assert locate_quote(PAGES[7], "Patient reports no relief after 12 weeks") is None
