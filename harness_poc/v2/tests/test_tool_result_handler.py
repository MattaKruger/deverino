"""Tests for _process_tool_result — A2 TDD micro-cycle."""

import pytest

from harness_poc.v2.contracts import (
    DELEGATED_OUTPUT_BLOCKED,
    DELEGATED_OUTPUT_COMPLETED,
    DELEGATED_OUTPUT_FAILED,
    DelegatedTaskOutput,
    DelegatedTaskResult,
)
from harness_poc.v2.handlers.tool_result_handler import (
    MalformedToolResultError,
    RetryableToolError,
    ToolTimeoutError,
    _process_tool_result,
)

# ====================================================================
# Phase 1: Failure-mode tests
# ====================================================================

class TestMalformedNotADict:
    """Failure mode: raw_result is not a dict-like object."""

    def test_none_input(self):
        with pytest.raises(MalformedToolResultError, match="dict"):
            _process_tool_result(None)

    def test_string_input(self):
        with pytest.raises(MalformedToolResultError, match="dict"):
            _process_tool_result("some string")

    def test_list_input(self):
        with pytest.raises(MalformedToolResultError, match="dict"):
            _process_tool_result([1, 2, 3])


class TestMalformedMissingFields:
    """Failure mode: dict-like but missing required fields."""

    def test_missing_task_id(self):
        with pytest.raises(MalformedToolResultError, match="task_id"):
            _process_tool_result({"status": "success"})

    def test_missing_status(self):
        with pytest.raises(MalformedToolResultError, match="status"):
            _process_tool_result({"task_id": "t1"})

    def test_empty_dict(self):
        with pytest.raises(MalformedToolResultError):
            _process_tool_result({})


# ====================================================================
# Phase 2: Edge-case tests
# ====================================================================

class TestMalformedInvalidStatus:
    """Edge case: valid shape but bogus status value."""

    def test_bogus_status_value(self):
        with pytest.raises(MalformedToolResultError, match="status"):
            _process_tool_result({"task_id": "t1", "status": "bogus"})

    def test_status_is_none(self):
        with pytest.raises(MalformedToolResultError, match="status"):
            _process_tool_result({"task_id": "t1", "status": None})

    def test_status_is_number(self):
        with pytest.raises(MalformedToolResultError, match="status"):
            _process_tool_result({"task_id": "t1", "status": 42})


class TestTimeoutRawResult:
    """Edge case: the raw result indicates a timeout."""

    def test_status_timeout_with_error_message(self):
        raw = {
            "task_id": "t-timeout",
            "status": "timeout",
            "error": "Task exceeded 30s deadline",
        }
        output = _process_tool_result(raw)
        assert isinstance(output, DelegatedTaskOutput)
        assert output.task_id == "t-timeout"
        assert output.output_label == DELEGATED_OUTPUT_FAILED
        assert output.metadata.get("timed_out") is True
        assert "timed out" in output.summary.lower()

    def test_status_timeout_no_error_field(self):
        raw = {"task_id": "t-to", "status": "timeout"}
        output = _process_tool_result(raw)
        assert output.output_label == DELEGATED_OUTPUT_FAILED
        assert output.metadata.get("timed_out") is True


class TestRetryableError:
    """Edge case: the raw result indicates a transient/retryable failure."""

    def test_retryable_429_rate_limit(self):
        raw = {
            "task_id": "t-rate",
            "status": "failed",
            "error": "429 Too Many Requests",
        }
        with pytest.raises(RetryableToolError, match="retry"):
            _process_tool_result(raw)

    def test_retryable_503_service_unavailable(self):
        raw = {
            "task_id": "t-503",
            "status": "failed",
            "error": "503 Service Unavailable",
        }
        with pytest.raises(RetryableToolError, match="retry"):
            _process_tool_result(raw)

    def test_retryable_connection_error(self):
        raw = {
            "task_id": "t-conn",
            "status": "failed",
            "error": "ConnectionError: connection reset by peer",
        }
        with pytest.raises(RetryableToolError, match="retry"):
            _process_tool_result(raw)

    def test_retryable_error_includes_task_id(self):
        raw = {
            "task_id": "t-retry-me",
            "status": "failed",
            "error": "503 Service Unavailable",
        }
        with pytest.raises(RetryableToolError) as exc_info:
            _process_tool_result(raw)
        assert exc_info.value.task_id == "t-retry-me"

    def test_non_retryable_failure_still_returns_output(self):
        raw = {
            "task_id": "t-permanent",
            "status": "failed",
            "error": "Permission denied: invalid API key",
        }
        output = _process_tool_result(raw)
        assert isinstance(output, DelegatedTaskOutput)
        assert output.output_label == DELEGATED_OUTPUT_FAILED


# ====================================================================
# Phase 3: Success-path tests
# ====================================================================

class TestSuccessPath:
    """Happy path: valid raw result with success status."""

    def test_minimal_success(self):
        raw = {"task_id": "t-ok", "status": "success"}
        output = _process_tool_result(raw)
        assert isinstance(output, DelegatedTaskOutput)
        assert output.task_id == "t-ok"
        assert output.output_label == DELEGATED_OUTPUT_COMPLETED

    def test_success_with_raw_output(self):
        raw = {
            "task_id": "t-data",
            "status": "success",
            "raw_output": {"answer": 42, "citations": ["a", "b"]},
        }
        output = _process_tool_result(raw)
        assert output.raw_output == {"answer": 42, "citations": ["a", "b"]}

    def test_success_creates_summary(self):
        raw = {"task_id": "t-sum", "status": "success"}
        output = _process_tool_result(raw)
        assert output.summary
        assert "completed" in output.summary.lower()

    def test_success_metadata_includes_status(self):
        raw = {"task_id": "t-meta", "status": "success"}
        output = _process_tool_result(raw)
        assert output.metadata.get("raw_status") == "success"


class TestFailedPath:
    """Non-retryable failure produces a DelegatedTaskOutput with failed label."""

    def test_permanent_failure(self):
        raw = {
            "task_id": "t-fail",
            "status": "failed",
            "error": "Tool not found: nonexistent_tool",
        }
        output = _process_tool_result(raw)
        assert output.output_label == DELEGATED_OUTPUT_FAILED
        assert output.task_id == "t-fail"

    def test_failure_preserves_error_in_summary(self):
        raw = {
            "task_id": "t-err",
            "status": "failed",
            "error": "Something went wrong",
        }
        output = _process_tool_result(raw)
        assert "Something went wrong" in output.summary


class TestBlockedRecovery:
    """When original_goal_status='blocked', failed maps to blocked output."""

    def test_blocked_recovery(self):
        raw = {"task_id": "t-blocked", "status": "failed", "error": "Dependency unmet"}
        output = _process_tool_result(raw, original_goal_status="blocked")
        assert output.output_label == DELEGATED_OUTPUT_BLOCKED

    def test_blocked_recovery_only_on_failure(self):
        raw = {"task_id": "t-ok-blocked", "status": "success"}
        output = _process_tool_result(raw, original_goal_status="blocked")
        assert output.output_label == DELEGATED_OUTPUT_COMPLETED


class TestDelegatedTaskResultInput:
    """Already-constructed DelegatedTaskResult objects should be accepted."""

    def test_accepts_delegated_task_result(self):
        dtr = DelegatedTaskResult(
            task_id="t-direct",
            status="success",
            raw_output={"direct": True},
        )
        output = _process_tool_result(dtr)
        assert output.task_id == "t-direct"
        assert output.output_label == DELEGATED_OUTPUT_COMPLETED
        assert output.raw_output == {"direct": True}

    def test_delegated_task_result_failed(self):
        dtr = DelegatedTaskResult(
            task_id="t-direct-fail",
            status="failed",
            error="Boom",
        )
        output = _process_tool_result(dtr)
        assert output.output_label == DELEGATED_OUTPUT_FAILED


class TestToolTimeoutErrorException:
    """ToolTimeoutError carries task_id."""

    def test_timeout_error_carries_task_id(self):
        err = ToolTimeoutError("t-to", "30s deadline exceeded")
        assert err.task_id == "t-to"
        assert "t-to" in str(err)
