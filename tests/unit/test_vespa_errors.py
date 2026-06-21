from __future__ import annotations

from harness_poc.core.retrieval.vespa_client import _response_error_message


def test_response_error_message_extracts_vespa_error() -> None:
    class Response:
        def __init__(self) -> None:
            self.status_code = 400
            self.json = {
                "errors": [
                    {
                        "message": (
                            "Operation contains invalid input: Field 'embedding' is not "
                            "part of the declared document type 'doc_chunk'"
                        )
                    }
                ]
            }

    message = _response_error_message(Response())

    assert message.startswith("HTTP 400:")
    assert "Field 'embedding' is not part of the declared document type" in message
