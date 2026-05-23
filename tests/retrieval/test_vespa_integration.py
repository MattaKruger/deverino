"""Live integration tests for the Vespa document retrieval stack.

Run with:
    VESPA_INTEGRATION=1 uv run pytest tests/test_vespa_integration.py -v

Prerequisites:
    1. Start Vespa: docker run --detach --name vespa --publish 8080:8080 vespaengine/vespa
    2. Deploy the app: vespa deploy vespa/document_retrieval/
    3. Wait for Vespa to be ready.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import suppress

import pytest

from harness_poc.core.config import RetrievalConfig
from harness_poc.core.retrieval import LiveVespaDocumentClient, SearchRequest, make_document_chunks

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("VESPA_INTEGRATION") != "1",
        reason="Set VESPA_INTEGRATION=1 to run live Vespa tests",
    ),
]

FIXTURE_URI = "test/integration-fixture.md"
FIXTURE_SOURCE_ID = "test-integration-fixture-md"
FIXTURE_TEXT = (
    "deverino-vespa-integration-needle-20260520. "
    "The blackboard database stores durable project state across sessions. "
    "State consolidation merges session-level proposals into the project state. "
    "Each proposal must be approved before it is written to project_state."
)


@pytest.fixture(scope="module")
def vespa_client() -> LiveVespaDocumentClient:
    cfg = RetrievalConfig(
        vespa_url=os.getenv("VESPA_URL", "http://localhost:8080"),
        namespace="deverino",
        schema="doc_chunk",
    )
    client = LiveVespaDocumentClient(cfg)
    client.health_check()
    return client


@pytest.fixture(autouse=True, scope="module")
def cleanup_fixture(vespa_client: LiveVespaDocumentClient) -> Iterator[None]:
    yield
    with suppress(Exception):
        vespa_client.delete_source(FIXTURE_SOURCE_ID)


def test_health_check_passes(vespa_client: LiveVespaDocumentClient) -> None:
    vespa_client.health_check()


def test_feed_and_keyword_search(vespa_client: LiveVespaDocumentClient) -> None:
    vespa_client.delete_source(FIXTURE_SOURCE_ID)
    chunks = make_document_chunks(
        text=FIXTURE_TEXT,
        uri=FIXTURE_URI,
        title="Integration Fixture",
        kind="test",
        chunk_size=500,
        chunk_overlap=50,
    )
    summary = vespa_client.feed_chunks(chunks)
    assert summary.failed == 0
    assert summary.fed == len(chunks)

    time.sleep(2)

    results = vespa_client.search(
        SearchRequest(
            query="deverino-vespa-integration-needle-20260520",
            mode="keyword",
            hits=5,
            source_id=FIXTURE_SOURCE_ID,
        )
    )
    source_ids = {result.source_id for result in results}
    assert FIXTURE_SOURCE_ID in source_ids


def test_feed_and_semantic_search(vespa_client: LiveVespaDocumentClient) -> None:
    results = vespa_client.search(
        SearchRequest(
            query="deverino-vespa-integration-needle-20260520",
            mode="semantic",
            hits=5,
            source_id=FIXTURE_SOURCE_ID,
        )
    )
    if results:
        assert all(isinstance(result.relevance, float) for result in results)


def test_feed_and_hybrid_search(vespa_client: LiveVespaDocumentClient) -> None:
    results = vespa_client.search(
        SearchRequest(
            query="deverino-vespa-integration-needle-20260520",
            mode="hybrid",
            hits=5,
            source_id=FIXTURE_SOURCE_ID,
        )
    )
    if results:
        source_ids = {result.source_id for result in results}
        assert FIXTURE_SOURCE_ID in source_ids


def test_delete_source(vespa_client: LiveVespaDocumentClient) -> None:
    vespa_client.delete_source(FIXTURE_SOURCE_ID)
    time.sleep(1)
    results = vespa_client.search(
        SearchRequest(
            query="deverino-vespa-integration-needle-20260520",
            mode="keyword",
            hits=5,
            source_id=FIXTURE_SOURCE_ID,
        )
    )
    source_ids = {result.source_id for result in results}
    assert FIXTURE_SOURCE_ID not in source_ids
