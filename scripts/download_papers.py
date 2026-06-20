#!/usr/bin/env python3
"""Download papers by arXiv ID, naming files by title instead of ID.

uv run python scripts/download_papers.py
"""

from __future__ import annotations

import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ARXIV_NS = "{http://www.w3.org/2005/Atom}"
OUTPUT_DIR = Path("docs/papers")
DOWNLOAD_DELAY = 3.0
MAX_SLUG_LENGTH = 120

# ── The 19 papers to download ─────────────────────────────────────────────
IDS = [
    "2507.01701",  # Blackboard Architecture
    "2605.18747",  # Code as Agent Harness
    "2603.03329",  # AutoHarness
    "2606.05922",  # Harness Optimization
    "2605.03353",  # SkCC
    "2605.27955",  # Skill-as-Pseudocode
    "2605.19362",  # Skill Specification Comprehension
    "2507.10593",  # ToolRegistry
    "2401.07324",  # Small LLMs Weak Tool Learners
    "2508.08322",  # Context Engineering
    "2603.19896",  # Utility-Guided Orchestration
    "2502.09809",  # AgentGuard
    "2508.02866",  # PROV-AGENT
    "2605.15425",  # Runtime Task Decomposition
    "2602.12311",  # Self-Reflection
    "2601.00828",  # LLM Self-Correction
    "2406.16739",  # Agent-Driven Improvement
    "2412.21139",  # SWE-Gym
    "2604.15468",  # Semi-Executable Stack
]


def fetch_title(arxiv_id: str) -> str:
    """Look up a paper's title from the arXiv API."""
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Deverino/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read().decode("utf-8"))
    entry = root.find(f"{ARXIV_NS}entry")
    if entry is None:
        return arxiv_id
    title_el = entry.find(f"{ARXIV_NS}title")
    return title_el.text.strip() if title_el is not None and title_el.text else arxiv_id


def title_to_filename(title: str, arxiv_id: str) -> str:
    """Convert a paper title to a safe filename."""
    # Remove version suffix from ID for clean filenames
    clean_id = re.sub(r"v\d+$", "", arxiv_id)
    # Clean title: lowercase, replace non-alphanumeric with underscores
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    # Truncate to reasonable length
    if len(slug) > MAX_SLUG_LENGTH:
        slug = slug[:MAX_SLUG_LENGTH].rstrip("_")
    return f"{slug}__{clean_id}.pdf"


def download_pdf(arxiv_id: str, filename: str) -> bool:
    """Download a PDF and save with the given filename."""
    filepath = OUTPUT_DIR / filename
    if filepath.exists():
        print(f"  Already exists, skipping: {filename}")
        return True

    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    print(f"  Downloading {filename[:80]}...", end=" ", flush=True)
    try:
        req = urllib.request.Request(pdf_url, headers={"User-Agent": "Deverino/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            filepath.write_bytes(resp.read())
        print("done.")
    except Exception as exc:
        print(f"FAILED: {exc}")
        return False
    else:
        return True


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    success = 0

    for i, arxiv_id in enumerate(IDS):
        print(f"\n[{i + 1}/{len(IDS)}] {arxiv_id}")

        # Fetch title (with delay to be polite)
        if i > 0:
            time.sleep(1.0)
        try:
            title = fetch_title(arxiv_id)
            print(f"  Title: {title}")
        except Exception as exc:
            print(f"  Failed to fetch title: {exc}")
            title = arxiv_id

        filename = title_to_filename(title, arxiv_id)
        if download_pdf(arxiv_id, filename):
            success += 1

        if i < len(IDS) - 1:
            time.sleep(DOWNLOAD_DELAY)

    print(f"\n{'=' * 60}")
    print(f"Done: {success}/{len(IDS)} downloaded to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
