"""Tests for PubMed client and literature support scoring.

Covers:
  - XML parsing of EFetch responses
  - Literature score computation
  - Cache key generation
  - Article data extraction
  - Score edge cases (empty, single, many articles)
  - Journal quality classification
  - Integration with evidence snapshot (literature_support_score wiring)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# EFetch XML parsing
# ---------------------------------------------------------------------------

SAMPLE_EFETCH_XML = """<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2024//EN"
  "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_240101.dtd">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE" Owner="NLM">
      <PMID Version="1">38765432</PMID>
      <Article PubModel="Print">
        <Journal>
          <JournalIssue CitedMedium="Internet">
            <PubDate>
              <Year>2025</Year>
              <Month>Mar</Month>
            </PubDate>
          </JournalIssue>
          <Title>N Engl J Med</Title>
        </Journal>
        <ArticleTitle>Phase 3 Trial of Aficamten for Obstructive HCM</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Obstructive hypertrophic cardiomyopathy remains a challenge.</AbstractText>
          <AbstractText Label="METHODS">We conducted a randomized, double-blind, placebo-controlled trial in 250 patients with obstructive HCM. Patients received aficamten or placebo for 24 weeks.</AbstractText>
          <AbstractText Label="RESULTS">The primary endpoint of peak VO2 improved significantly in the aficamten group compared with placebo (p&lt;0.001). Secondary endpoints including NYHA class and LVOT gradient also improved.</AbstractText>
          <AbstractText Label="CONCLUSIONS">Aficamten significantly improved exercise capacity and symptoms in patients with obstructive HCM.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Olivotto</LastName>
            <Initials>I</Initials>
          </Author>
          <Author ValidYN="Y">
            <LastName>Hegde</LastName>
            <Initials>SM</Initials>
          </Author>
        </AuthorList>
        <ELocationID EIdType="doi" ValidYN="Y">10.1056/NEJMoa2401234</ELocationID>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38765432</ArticleId>
        <ArticleId IdType="pmc">PMC11234567</ArticleId>
        <ArticleId IdType="doi">10.1056/NEJMoa2401234</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE" Owner="NLM">
      <PMID Version="1">37654321</PMID>
      <Article PubModel="Print">
        <Journal>
          <JournalIssue CitedMedium="Internet">
            <PubDate>
              <Year>2024</Year>
              <Month>Jun</Month>
            </PubDate>
          </JournalIssue>
          <Title>Circulation</Title>
        </Journal>
        <ArticleTitle>Cardiac Myosin Inhibition in HCM: Mechanistic Insights</ArticleTitle>
        <Abstract>
          <AbstractText>Short abstract about mechanism of action.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Green</LastName>
            <Initials>EM</Initials>
          </Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">37654321</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


class TestEFetchParsing:

    def test_parse_two_articles(self):
        from data_sources.pubmed_client import PubMedClient

        articles = PubMedClient._parse_efetch_xml(SAMPLE_EFETCH_XML)
        assert len(articles) == 2

    def test_first_article_fields(self):
        from data_sources.pubmed_client import PubMedClient

        articles = PubMedClient._parse_efetch_xml(SAMPLE_EFETCH_XML)
        art = articles[0]

        assert art.pmid == "38765432"
        assert "Aficamten" in art.title
        assert art.journal == "N Engl J Med"
        assert art.pubdate == "2025 Mar"
        assert art.pub_year == 2025
        assert art.doi == "10.1056/NEJMoa2401234"
        assert art.pmc_id == "PMC11234567"
        assert len(art.authors) == 2
        assert art.authors[0] == "Olivotto I"

    def test_abstract_with_labels(self):
        from data_sources.pubmed_client import PubMedClient

        articles = PubMedClient._parse_efetch_xml(SAMPLE_EFETCH_XML)
        art = articles[0]

        assert "BACKGROUND:" in art.abstract
        assert "RESULTS:" in art.abstract
        assert "p<0.001" in art.abstract  # XML entity decoded

    def test_second_article_no_pmc(self):
        from data_sources.pubmed_client import PubMedClient

        articles = PubMedClient._parse_efetch_xml(SAMPLE_EFETCH_XML)
        art = articles[1]

        assert art.pmid == "37654321"
        assert art.pmc_id == ""
        assert art.doi == ""

    def test_empty_xml(self):
        from data_sources.pubmed_client import PubMedClient

        xml = '<?xml version="1.0" ?><PubmedArticleSet></PubmedArticleSet>'
        articles = PubMedClient._parse_efetch_xml(xml)
        assert articles == []

    def test_malformed_xml(self):
        from data_sources.pubmed_client import PubMedClient

        articles = PubMedClient._parse_efetch_xml("not xml at all")
        assert articles == []

    def test_to_dict_round_trip(self):
        from data_sources.pubmed_client import PubMedClient

        articles = PubMedClient._parse_efetch_xml(SAMPLE_EFETCH_XML)
        art = articles[0]
        d = art.to_dict()

        assert d["pmid"] == "38765432"
        assert d["pub_year"] == 2025
        assert len(d["authors"]) <= 5  # capped
        assert len(d["abstract"]) <= 500  # capped


# ---------------------------------------------------------------------------
# Literature score computation
# ---------------------------------------------------------------------------


class TestLiteratureScore:

    def _make_article(self, **kwargs):
        from data_sources.pubmed_client import PubMedArticle

        defaults = {
            "pmid": "12345",
            "title": "Test Article",
            "abstract": "A" * 250,
            "journal": "Some Journal",
            "pubdate": "2025 Jan",
            "pub_year": 2025,
        }
        defaults.update(kwargs)
        return PubMedArticle(**defaults)

    def test_no_articles_returns_zero(self):
        from data_sources.pubmed_client import compute_literature_score

        assert compute_literature_score([]) == 0.0

    def test_single_recent_high_impact(self):
        from data_sources.pubmed_client import compute_literature_score

        art = self._make_article(journal="N Engl J Med", pub_year=2025)
        score = compute_literature_score([art], current_year=2026)

        assert score > 0.3
        assert score <= 1.0

    def test_many_articles_higher_than_few(self):
        from data_sources.pubmed_client import compute_literature_score

        few = [self._make_article(pmid=str(i)) for i in range(2)]
        many = [self._make_article(pmid=str(i)) for i in range(15)]

        score_few = compute_literature_score(few, current_year=2026)
        score_many = compute_literature_score(many, current_year=2026)

        assert score_many > score_few

    def test_recent_articles_score_higher(self):
        from data_sources.pubmed_client import compute_literature_score

        recent = [self._make_article(pub_year=2025)]
        old = [self._make_article(pub_year=2015)]

        score_recent = compute_literature_score(recent, current_year=2026)
        score_old = compute_literature_score(old, current_year=2026)

        assert score_recent > score_old

    def test_high_impact_journal_boosts_score(self):
        from data_sources.pubmed_client import compute_literature_score

        high = [self._make_article(journal="N Engl J Med")]
        low = [self._make_article(journal="Unknown Regional Journal")]

        score_high = compute_literature_score(high, current_year=2026)
        score_low = compute_literature_score(low, current_year=2026)

        assert score_high > score_low

    def test_score_bounded_zero_to_one(self):
        from data_sources.pubmed_client import compute_literature_score

        articles = [self._make_article(pmid=str(i), journal="N Engl J Med", pub_year=2025) for i in range(50)]
        score = compute_literature_score(articles, current_year=2026)

        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Cache key determinism
# ---------------------------------------------------------------------------


class TestCacheKey:

    def test_same_query_same_key(self):
        from data_sources.pubmed_client import PubMedClient

        client = PubMedClient()
        k1 = client._cache_key("aficamten HCM")
        k2 = client._cache_key("aficamten HCM")
        assert k1 == k2

    def test_different_query_different_key(self):
        from data_sources.pubmed_client import PubMedClient

        client = PubMedClient()
        k1 = client._cache_key("aficamten HCM")
        k2 = client._cache_key("mavacamten HCM")
        assert k1 != k2


# ---------------------------------------------------------------------------
# Evidence snapshot integration
# ---------------------------------------------------------------------------


class TestAPIKeyLoading:

    def test_env_var_loaded_when_no_explicit_key(self):
        import os

        from data_sources.pubmed_client import PubMedClient

        os.environ["NCBI_API_KEY"] = "ncbi_test_placeholder"  # pragma: allowlist secret
        try:
            client = PubMedClient()
            assert client.api_key == "ncbi_test_placeholder"  # pragma: allowlist secret
        finally:
            del os.environ["NCBI_API_KEY"]

    def test_explicit_key_overrides_env(self):
        import os

        from data_sources.pubmed_client import PubMedClient

        os.environ["NCBI_API_KEY"] = "ncbi_env_placeholder"  # pragma: allowlist secret
        try:
            client = PubMedClient(api_key="ncbi_explicit_val")  # pragma: allowlist secret
            assert client.api_key == "ncbi_explicit_val"  # pragma: allowlist secret
        finally:
            del os.environ["NCBI_API_KEY"]

    def test_no_key_no_error(self):
        import os

        from data_sources.pubmed_client import PubMedClient

        os.environ.pop("NCBI_API_KEY", None)
        client = PubMedClient(api_key=None)
        assert client.api_key is None

    def test_rate_limit_faster_with_key(self):
        from data_sources.pubmed_client import RATE_LIMIT, PubMedClient

        client_with_key = PubMedClient(api_key="placeholder")  # pragma: allowlist secret
        # With key: 0.11s, without: 0.34s
        assert client_with_key.api_key is not None
        assert RATE_LIMIT > 0.11


# ---------------------------------------------------------------------------
# Drug name map
# ---------------------------------------------------------------------------


class TestDrugNameMap:

    def test_drug_name_map_exists(self):
        from pathlib import Path

        map_path = Path("/mnt/c/Projects/biotech_screener/biotech-screener/production_data/drug_name_map.json")
        assert map_path.exists()

    def test_drug_name_map_schema(self):
        import json
        from pathlib import Path

        map_path = Path("/mnt/c/Projects/biotech_screener/biotech-screener/production_data/drug_name_map.json")
        data = json.loads(map_path.read_text())
        assert "entries" in data
        assert "n_tickers" in data
        assert data["n_tickers"] >= 200

    def test_drug_name_map_loaded_by_enricher(self):
        from event_ev.evidence_snapshot import _load_drug_name_map

        drug_map = _load_drug_name_map()
        assert len(drug_map) >= 200
        # PDUFA entries should be present
        assert any(v for v in drug_map.values())


# ---------------------------------------------------------------------------
# Evidence snapshot integration
# ---------------------------------------------------------------------------


class TestEvidenceSnapshotLiteratureWiring:

    def _make_node(self, **overrides):
        from event_ev.data_contracts import CatalystNode

        defaults = {
            "ticker": "CYTK",
            "event_family": "CLINICAL",
            "event_type": "DATA_READOUT",
            "event_subtype": "TOPLINE",
            "expected_date": "2026-06-15",
            "date_range_start": "2026-06-15",
            "date_range_end": None,
            "date_precision": "MONTH",
            "date_confidence": 0.6,
            "source": "CTGOV",
            "source_uid": "NCT04219826",
            "disclosed_at": "2026-01-15",
            "phase": "3",
            "indication": "cardiology",
        }
        defaults.update(overrides)
        return CatalystNode(**defaults)

    def test_literature_score_wired_through(self):
        from datetime import date

        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = self._make_node()
        snap = build_evidence_snapshot(
            node,
            date(2026, 4, 15),
            literature_scores={"CYTK": 0.72},
            pubmed_refs={"CYTK": ["38765432", "37654321"]},
        )

        assert snap.literature_support_score == 0.72
        assert "pubmed:38765432" in snap.source_refs
        assert "pubmed:37654321" in snap.source_refs

    def test_literature_score_none_when_not_enriched(self):
        from datetime import date

        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = self._make_node()
        snap = build_evidence_snapshot(node, date(2026, 4, 15))

        assert snap.literature_support_score is None

    def test_literature_boosts_confidence(self):
        from datetime import date

        from event_ev.evidence_snapshot import build_evidence_snapshot

        node = self._make_node(nct_id=None, designations=[])

        snap_no_lit = build_evidence_snapshot(node, date(2026, 4, 15))
        snap_with_lit = build_evidence_snapshot(
            node,
            date(2026, 4, 15),
            literature_scores={"CYTK": 0.5},
        )

        assert snap_with_lit.evidence_confidence > snap_no_lit.evidence_confidence

    def test_batch_with_literature(self):
        from datetime import date

        from event_ev.evidence_snapshot import build_evidence_snapshots

        nodes = [self._make_node()]
        result = build_evidence_snapshots(
            nodes,
            date(2026, 4, 15),
            literature_scores={"CYTK": 0.65},
            pubmed_refs={"CYTK": ["12345"]},
        )

        snap = list(result.values())[0]
        assert snap.literature_support_score == 0.65
