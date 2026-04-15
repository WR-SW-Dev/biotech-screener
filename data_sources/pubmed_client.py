"""PubMed client via NCBI E-utilities.

Searches PubMed for publications related to a drug/target/indication and
retrieves article metadata (title, journal, date, abstract, PMID, DOI).

API docs: https://www.ncbi.nlm.nih.gov/books/NBK25500/
Rate limit: 3 requests/second without API key, 10/s with key.
No authentication required for basic usage.

Cache: disk-based JSON cache in data/cache/pubmed/ (24h TTL default).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RATE_LIMIT = 0.34  # ~3 requests/sec (no API key)
MAX_RESULTS_PER_SEARCH = 20

_REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = _REPO_ROOT / "data" / "cache" / "pubmed"

# High-impact biotech/pharma journals for scoring
_HIGH_IMPACT_JOURNALS = frozenset(
    {
        "n engl j med",
        "lancet",
        "lancet oncol",
        "jama",
        "jama oncol",
        "j clin oncol",
        "nat med",
        "nat rev drug discov",
        "cell",
        "science",
        "nature",
        "blood",
        "j clin invest",
        "ann oncol",
        "eur heart j",
        "circulation",
    }
)

_MID_IMPACT_JOURNALS = frozenset(
    {
        "clin cancer res",
        "cancer discov",
        "mol ther",
        "leukemia",
        "br j haematol",
        "haematologica",
        "eur j cancer",
        "ann intern med",
        "bmj",
        "gastroenterology",
        "hepatology",
        "j hepatol",
        "gut",
        "am j hum genet",
        "genet med",
    }
)


class PubMedArticle:
    """Parsed PubMed article metadata."""

    __slots__ = (
        "pmid",
        "title",
        "abstract",
        "journal",
        "pubdate",
        "doi",
        "pmc_id",
        "authors",
        "pub_year",
    )

    def __init__(
        self,
        pmid: str,
        title: str = "",
        abstract: str = "",
        journal: str = "",
        pubdate: str = "",
        doi: str = "",
        pmc_id: str = "",
        authors: Optional[List[str]] = None,
        pub_year: Optional[int] = None,
    ) -> None:
        self.pmid = pmid
        self.title = title
        self.abstract = abstract
        self.journal = journal
        self.pubdate = pubdate
        self.doi = doi
        self.pmc_id = pmc_id
        self.authors = authors or []
        self.pub_year = pub_year

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pmid": self.pmid,
            "title": self.title,
            "abstract": self.abstract[:500] if self.abstract else "",
            "journal": self.journal,
            "pubdate": self.pubdate,
            "doi": self.doi,
            "pmc_id": self.pmc_id,
            "authors": self.authors[:5],
            "pub_year": self.pub_year,
        }


class PubMedClient:
    """Client for NCBI E-utilities (PubMed search and fetch).

    Usage:
        client = PubMedClient()
        articles = client.search_drug("aficamten", indication="HCM")
        articles = client.search_nct("NCT04219826")
    """

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        cache_ttl_hours: int = 24,
        api_key: Optional[str] = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_hours = cache_ttl_hours
        self.api_key = api_key
        self._last_request = 0.0

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        wait = (0.11 if self.api_key else RATE_LIMIT) - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _get(self, endpoint: str, params: Dict[str, str]) -> Optional[str]:
        """Make a GET request to E-utilities, return raw response text."""
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{EUTILS_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
        self._rate_limit()

        req = urllib.request.Request(url, headers={"Accept": "application/xml"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            logger.warning("PubMed request failed for %s: %s", endpoint, exc)
            return None
        except Exception as exc:
            logger.error("PubMed unexpected error for %s: %s", endpoint, exc)
            return None

    def _read_cache(self, key: str) -> Optional[List[Dict[str, Any]]]:
        cache_file = self.cache_dir / f"{key}.json"
        if not cache_file.exists():
            return None
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if (datetime.now() - mtime).total_seconds() > self.cache_ttl_hours * 3600:
            return None
        try:
            return json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, key: str, articles: List[Dict[str, Any]]) -> None:
        cache_file = self.cache_dir / f"{key}.json"
        try:
            cache_file.write_text(json.dumps(articles, indent=2))
        except OSError as exc:
            logger.debug("Cache write failed for %s: %s", key, exc)

    def _cache_key(self, query: str) -> str:
        return hashlib.sha1(query.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_drug(
        self,
        drug_name: str,
        indication: str = "",
        max_results: int = MAX_RESULTS_PER_SEARCH,
    ) -> List[PubMedArticle]:
        """Search PubMed for a drug name, optionally scoped by indication.

        Returns articles sorted by relevance (PubMed default).
        """
        parts = [drug_name]
        if indication and indication.lower() != "unknown":
            parts.append(indication)
        query = " AND ".join(f'"{p}"' for p in parts)

        cache_key = self._cache_key(f"drug_{query}")
        cached = self._read_cache(cache_key)
        if cached is not None:
            return [self._dict_to_article(d) for d in cached]

        pmids = self._esearch(query, max_results)
        if not pmids:
            self._write_cache(cache_key, [])
            return []

        articles = self._efetch(pmids)
        self._write_cache(cache_key, [a.to_dict() for a in articles])
        return articles

    def search_nct(self, nct_id: str, max_results: int = 10) -> List[PubMedArticle]:
        """Search PubMed for articles referencing a ClinicalTrials.gov NCT ID."""
        if not nct_id:
            return []
        query = nct_id

        cache_key = self._cache_key(f"nct_{nct_id}")
        cached = self._read_cache(cache_key)
        if cached is not None:
            return [self._dict_to_article(d) for d in cached]

        pmids = self._esearch(query, max_results)
        if not pmids:
            self._write_cache(cache_key, [])
            return []

        articles = self._efetch(pmids)
        self._write_cache(cache_key, [a.to_dict() for a in articles])
        return articles

    def _esearch(self, query: str, max_results: int) -> List[str]:
        """ESearch: find PMIDs matching a query."""
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": str(max_results),
            "retmode": "xml",
            "sort": "relevance",
        }
        xml_text = self._get("esearch.fcgi", params)
        if not xml_text:
            return []

        try:
            root = ET.fromstring(xml_text)
            return [id_el.text for id_el in root.findall(".//Id") if id_el.text]
        except ET.ParseError as exc:
            logger.warning("PubMed esearch XML parse error: %s", exc)
            return []

    def _efetch(self, pmids: List[str]) -> List[PubMedArticle]:
        """EFetch: retrieve article metadata for a list of PMIDs."""
        if not pmids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        xml_text = self._get("efetch.fcgi", params)
        if not xml_text:
            return []

        return self._parse_efetch_xml(xml_text)

    # ------------------------------------------------------------------
    # XML parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_efetch_xml(xml_text: str) -> List[PubMedArticle]:
        """Parse EFetch XML response into PubMedArticle objects."""
        articles = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning("PubMed efetch XML parse error: %s", exc)
            return []

        for art_el in root.findall(".//PubmedArticle"):
            try:
                articles.append(PubMedClient._parse_article(art_el))
            except Exception as exc:
                logger.debug("Failed to parse PubMed article: %s", exc)
                continue
        return articles

    @staticmethod
    def _parse_article(art_el: ET.Element) -> PubMedArticle:
        """Parse a single PubmedArticle XML element."""
        medline = art_el.find(".//MedlineCitation")
        article = medline.find("Article") if medline is not None else None

        pmid = ""
        pmid_el = medline.find("PMID") if medline is not None else None
        if pmid_el is not None and pmid_el.text:
            pmid = pmid_el.text

        title = ""
        title_el = article.find("ArticleTitle") if article is not None else None
        if title_el is not None:
            title = "".join(title_el.itertext()).strip()

        # Abstract
        abstract = ""
        abs_el = article.find(".//Abstract") if article is not None else None
        if abs_el is not None:
            parts = []
            for text_el in abs_el.findall("AbstractText"):
                label = text_el.get("Label", "")
                text = "".join(text_el.itertext()).strip()
                if label:
                    parts.append(f"{label}: {text}")
                else:
                    parts.append(text)
            abstract = " ".join(parts)

        # Journal
        journal = ""
        journal_el = article.find(".//Journal/Title") if article is not None else None
        if journal_el is not None and journal_el.text:
            journal = journal_el.text

        # Pub date
        pubdate = ""
        pub_year = None
        date_el = article.find(".//Journal/JournalIssue/PubDate") if article is not None else None
        if date_el is not None:
            year_el = date_el.find("Year")
            month_el = date_el.find("Month")
            if year_el is not None and year_el.text:
                pub_year = int(year_el.text)
                pubdate = year_el.text
                if month_el is not None and month_el.text:
                    pubdate = f"{year_el.text} {month_el.text}"

        # DOI
        doi = ""
        for id_el in article.findall(".//ELocationID") if article is not None else []:
            if id_el.get("EIdType") == "doi" and id_el.text:
                doi = id_el.text
                break

        # PMC ID
        pmc_id = ""
        pmc_data = art_el.find(".//PubmedData")
        if pmc_data is not None:
            for id_el in pmc_data.findall(".//ArticleId"):
                if id_el.get("IdType") == "pmc" and id_el.text:
                    pmc_id = id_el.text
                    break

        # Authors
        authors = []
        author_list = article.find(".//AuthorList") if article is not None else None
        if author_list is not None:
            for author_el in author_list.findall("Author"):
                last = author_el.find("LastName")
                init = author_el.find("Initials")
                if last is not None and last.text:
                    name = last.text
                    if init is not None and init.text:
                        name += f" {init.text}"
                    authors.append(name)

        return PubMedArticle(
            pmid=pmid,
            title=title,
            abstract=abstract,
            journal=journal,
            pubdate=pubdate,
            doi=doi,
            pmc_id=pmc_id,
            authors=authors,
            pub_year=pub_year,
        )

    @staticmethod
    def _dict_to_article(d: Dict[str, Any]) -> PubMedArticle:
        return PubMedArticle(
            pmid=d.get("pmid", ""),
            title=d.get("title", ""),
            abstract=d.get("abstract", ""),
            journal=d.get("journal", ""),
            pubdate=d.get("pubdate", ""),
            doi=d.get("doi", ""),
            pmc_id=d.get("pmc_id", ""),
            authors=d.get("authors", []),
            pub_year=d.get("pub_year"),
        )


# ======================================================================
# Literature support scoring
# ======================================================================


def compute_literature_score(
    articles: List[PubMedArticle],
    current_year: int = 2026,
) -> float:
    """Compute a literature support score from PubMed articles.

    Score components (all normalized to [0, 1], then averaged):
      - publication_count: log-scaled count of relevant articles
      - recency: fraction of articles published in the last 3 years
      - journal_quality: fraction in high/mid-impact journals
      - has_results: whether any article has a substantial abstract

    Returns:
        Float in [0.0, 1.0]. 0.0 = no literature found.
    """
    if not articles:
        return 0.0

    n = len(articles)

    # 1. Publication count (log-scaled, saturates around 20+)
    import math

    count_score = min(math.log1p(n) / math.log1p(20), 1.0)

    # 2. Recency: fraction published in last 3 years
    recent = sum(1 for a in articles if a.pub_year and a.pub_year >= current_year - 3)
    recency_score = recent / n if n > 0 else 0.0

    # 3. Journal quality
    high = 0
    mid = 0
    for a in articles:
        jl = a.journal.lower().strip()
        if jl in _HIGH_IMPACT_JOURNALS:
            high += 1
        elif jl in _MID_IMPACT_JOURNALS:
            mid += 1
    quality_score = min((high * 1.0 + mid * 0.5) / max(n, 1), 1.0)

    # 4. Has results (any article with non-trivial abstract)
    has_results = any(len(a.abstract) > 200 for a in articles)
    results_score = 1.0 if has_results else 0.0

    # Weighted average
    score = 0.30 * count_score + 0.25 * recency_score + 0.25 * quality_score + 0.20 * results_score
    return round(min(score, 1.0), 4)
