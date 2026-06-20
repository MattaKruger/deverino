#!/usr/bin/env python3
"""Search arXiv for papers and download them to docs/papers/.

uv run python scripts/search_arxiv.py "agentic engineering"
uv run python scripts/search_arxiv.py "agentic engineering" --download
uv run python scripts/search_arxiv.py "agentic engineering" --max-results 20 --download
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

# arXiv API namespace
ARXIV_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_API = "http://export.arxiv.org/api/query"
DOWNLOAD_DELAY = 3.0  # seconds between downloads to be polite
MAX_AUTHORS_DISPLAY = 3
SUMMARY_TRUNCATE = 200


@dataclass
class Paper:
    """A paper returned by the arXiv API."""

    arxiv_id: str
    title: str
    authors: list[str]
    summary: str
    published: str
    pdf_url: str
    primary_category: str
    categories: list[str]


def search_arxiv(query: str, max_results: int = 10) -> list[Paper]:
    """Search arXiv and return matching papers."""
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"

    print(f"Searching arXiv for: {query}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Deverino/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode("utf-8")

    return _parse_atom(raw)


def _parse_atom(xml_text: str) -> list[Paper]:
    """Parse arXiv Atom XML response into Paper objects."""
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []

    for entry in root.findall(f"{ARXIV_NS}entry"):
        arxiv_id = _text(entry, f"{ARXIV_NS}id")
        # Strip the URL prefix to get just the ID (e.g., "2301.12345")
        arxiv_id = arxiv_id.rsplit("/", 1)[-1] if "/" in arxiv_id else arxiv_id

        title = _text(entry, f"{ARXIV_NS}title").strip()
        summary = _text(entry, f"{ARXIV_NS}summary").strip()

        authors = [
            _text(author, f"{ARXIV_NS}name") for author in entry.findall(f"{ARXIV_NS}author")
        ]

        published = _text(entry, f"{ARXIV_NS}published")

        # Build PDF URL from the ID
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        # Categories
        primary = entry.find(f"{ARXIV_NS}primary_category")
        primary_category = primary.attrib.get("term", "") if primary is not None else ""

        categories = [cat.attrib.get("term", "") for cat in entry.findall(f"{ARXIV_NS}category")]

        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                summary=summary,
                published=published,
                pdf_url=pdf_url,
                primary_category=primary_category,
                categories=categories,
            )
        )

    return papers


def _text(element: ET.Element, tag: str) -> str:
    """Safely extract text from an XML element."""
    child = element.find(tag)
    return child.text or "" if child is not None else ""


def display_papers(papers: list[Paper]) -> None:
    """Print a formatted list of papers to stdout."""
    if not papers:
        print("No results found.")
        return

    print(f"\n{'=' * 80}")
    print(f"Found {len(papers)} papers:\n")

    for i, paper in enumerate(papers, 1):
        authors_str = ", ".join(paper.authors[:MAX_AUTHORS_DISPLAY])
        if len(paper.authors) > MAX_AUTHORS_DISPLAY:
            authors_str += f" et al. ({len(paper.authors)} authors)"

        print(f"  [{i}] {paper.title}")
        print(f"      Authors:    {authors_str}")
        print(f"      arXiv ID:   {paper.arxiv_id}")
        print(f"      Published:  {paper.published[:10]}")
        print(f"      Category:   {paper.primary_category}")
        print(f"      PDF:        {paper.pdf_url}")
        # Truncate summary
        summary = paper.summary.replace("\n", " ")[:SUMMARY_TRUNCATE]
        if len(paper.summary) > SUMMARY_TRUNCATE:
            summary += "..."
        print(f"      Summary:    {summary}")
        print()


def download_paper(paper: Paper, output_dir: Path) -> bool:
    """Download a paper's PDF to the output directory.

    Returns True on success, False on failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{paper.arxiv_id}.pdf"
    filepath = output_dir / filename

    if filepath.exists():
        print(f"  [{paper.arxiv_id}] Already exists, skipping.")
        return True

    print(f"  [{paper.arxiv_id}] Downloading {paper.title[:60]}...", end=" ", flush=True)
    try:
        req = urllib.request.Request(paper.pdf_url, headers={"User-Agent": "Deverino/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            filepath.write_bytes(response.read())
        print("done.")
    except Exception as exc:
        print(f"FAILED: {exc}")
        return False
    else:
        return True


def download_papers(
    papers: list[Paper],
    output_dir: Path,
    selection: list[int] | None = None,
) -> None:
    """Download papers, optionally filtered by selection indices."""
    selected = [papers[i - 1] for i in selection if 1 <= i <= len(papers)] if selection else papers

    if not selected:
        print("No papers selected for download.")
        return

    print(f"\nDownloading {len(selected)} paper(s) to {output_dir}/ ...\n")

    success = 0
    for i, paper in enumerate(selected):
        if download_paper(paper, output_dir):
            success += 1
        if i < len(selected) - 1:
            time.sleep(DOWNLOAD_DELAY)

    print(f"\nDownloaded {success}/{len(selected)} paper(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search arXiv for papers and optionally download them.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python scripts/search_arxiv.py "agentic engineering"
  uv run python scripts/search_arxiv.py "agentic engineering" --download
  uv run python scripts/search_arxiv.py "agentic engineering" -n 20 --download
  uv run python scripts/search_arxiv.py "agentic engineering" --download 1 3 5
        """,
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="agentic engineering",
        help="Search query (default: 'agentic engineering')",
    )
    parser.add_argument(
        "-n",
        "--max-results",
        type=int,
        default=10,
        help="Maximum number of results (default: 10)",
    )
    parser.add_argument(
        "-d",
        "--download",
        nargs="*",
        type=int,
        metavar="N",
        help="Download papers. Optionally specify paper indices (1-based) to download specific ones. "
        "Without indices, downloads all listed papers.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("docs/papers"),
        help="Output directory for downloads (default: docs/papers)",
    )
    args = parser.parse_args()

    try:
        papers = search_arxiv(args.query, max_results=args.max_results)
    except Exception as exc:
        print(f"Search failed: {exc}", file=sys.stderr)
        sys.exit(1)

    display_papers(papers)

    if args.download is not None:
        # args.download is a list: empty list means --download (all), otherwise specific indices
        selection = args.download or None
        try:
            download_papers(papers, args.output_dir, selection=selection)
        except Exception as exc:
            print(f"Download failed: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
