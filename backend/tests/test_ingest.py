import pytest

from app.ingest.chunker import MAX_TOKENS, est_tokens
from app.ingest.overrides import parse_override
from app.ingest.pdf import join_lines

OVERRIDDEN_PAGES = {7, 9, 10, 16, 17}


def test_join_lines_is_cjk_aware():
    assert join_lines(["在保單生效第四至", "第九年內"]) == "在保單生效第四至第九年內"
    assert join_lines(["Basic Sum", "Insured"]) == "Basic Sum Insured"
    assert join_lines(["last-in-", "first-out"]) == "last-in-first-out"


def test_parse_override_front_matter_and_headings():
    page, meta = parse_override("---\nreason: table\n---\n# Title\n\n## Head\nline 1\nline 2\n\npara 2\n", "doc", 3)
    assert meta["reason"] == "table"
    assert [(b.kind, b.text) for b in page.blocks] == [
        ("title", "Title"),
        ("heading", "Head"),
        ("text", "line 1\nline 2"),
        ("text", "para 2"),
    ]
    assert page.source == "override" and page.number == 3


def test_every_page_is_chunked_and_ids_are_unique(corpus):
    pages = {c.page for c in corpus.chunks}
    assert pages == set(range(1, 21))
    ids = [c.id for c in corpus.chunks]
    assert len(ids) == len(set(ids))


def test_chunks_respect_token_budget(corpus):
    # A single oversized paragraph may exceed the budget slightly; nothing should be far over.
    assert max(est_tokens(c.text) for c in corpus.chunks) <= MAX_TOKENS * 1.2


def test_overrides_are_applied(corpus):
    sources = {c.page: c.source for c in corpus.chunks}
    assert {p for p, s in sources.items() if s == "override"} == OVERRIDDEN_PAGES
    assert corpus.override_pages["flexi-ulife-prime-saver"] == sorted(OVERRIDDEN_PAGES)


def test_font_errata_fixed(corpus):
    text = "\n".join(c.text for c in corpus.chunks)
    assert "籍" not in text and "�" not in text
    assert "曾提取的總金額" in text  # Note 4


def test_footnote_markers_link_to_notes(corpus):
    gio = [c for c in corpus.chunks if "Guaranteed Insurability Option[Note 3]" in c.text]
    assert gio, "superscript footnote digits should become [Note n] markers"


@pytest.mark.parametrize(
    "needle, page",
    [
        ("2.5% p.a.", 8),  # guaranteed interest
        ("365 days", 11),  # unemployment protection
        ("Cash Value = 賬戶價值 Account Value - 適用的退保費用", 10),
        ("| FP180/280 | ≥ Age 45 歲 | US$8,000", 17),
        ("21 calendar days", 15),  # cooling-off
    ],
)
def test_key_facts_land_on_the_right_page(corpus, needle, page):
    hits = [c.page for c in corpus.chunks if needle in c.text]
    assert page in hits, f"{needle!r} not found on page {page} (found on {hits})"


def test_packed_chunks_name_every_sub_section(corpus):
    """A chunk packing several short sections keeps its first heading as the retrieval label but
    shows all of them, so a citation of the suicide exclusion doesn't read "Inflation Risk"."""
    c = next(c for c in corpus.chunks if c.page == 14 and "Key Exclusions" in c.text and c.lang == "en")
    assert c.section.endswith("Inflation Risk")
    assert c.display_section.endswith("Inflation Risk · Credit Risk · Key Exclusions")
    single = next(c for c in corpus.chunks if c.page == 13 and c.lang == "en")
    assert single.display_section == single.section
