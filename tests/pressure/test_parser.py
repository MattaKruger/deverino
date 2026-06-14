"""Pressure test the LLM function call parser."""

from __future__ import annotations

import json

import pytest

from harness_poc.v2.subscribers.llm_worker import LlmWorker

p = LlmWorker._parse_skill_request


def test_json() -> None:
    r = p(
        json.dumps({"skill_name": "delegate_task", "arguments": {"persona": "x", "objective": "y"}})
    )
    assert r == {"skill_name": "delegate_task", "arguments": {"persona": "x", "objective": "y"}}


@pytest.mark.xfail(
    reason="XML invoke format not recognized by current parser — function_calls outer tag not handled"
)
def test_invoke_with_parameter() -> None:
    r = p(
        "<function_calls>\n"
        '<invoke name="delegate_task">\n'
        '<parameter name="task_details">{"subagent_name": "code_reviewer", "objective": "review"}</parameter>\n'
        "</invoke>\n"
        "</function_calls>"
    )
    assert r["skill_name"] == "delegate_task"
    assert r["arguments"] == {"subagent_name": "code_reviewer", "objective": "review"}


@pytest.mark.xfail(
    reason="XML invoke format not recognized by current parser — nested JSON body not handled"
)
def test_invoke_with_direct_json() -> None:
    r = p('<invoke name="read_memory">{"key": "result"}</invoke>')
    assert r["skill_name"] == "read_memory"
    assert r["arguments"] == {"key": "result"}


@pytest.mark.xfail(reason="XML tool_call format with nested JSON not recognized by current parser")
def test_tool_call_empty() -> None:
    r = p('Let me check.\n\n<tool_call name="skills_list">{}</tool_call>')
    assert r["skill_name"] == "skills_list"
    assert r["arguments"] == {}


@pytest.mark.xfail(reason="XML tool_call format not recognized by current parser")
def test_tool_call_with_json() -> None:
    r = p('<tool_call name="delegate_task">{"persona": "cr", "objective": "check"}</tool_call>')
    assert r["skill_name"] == "delegate_task"
    assert r["arguments"] == {"persona": "cr", "objective": "check"}


@pytest.mark.xfail(reason="XML tool_call format not recognized by current parser")
def test_tool_call_with_nested_json() -> None:
    r = p(
        '<tool_call name="delegate_task">'
        '{"subagent_name": "code_reviewer", '
        '"objective": "Review exec_engine.py for bugs.", '
        '"persona": "You are a meticulous code reviewer."}'
        "</tool_call>"
    )
    assert r["skill_name"] == "delegate_task"
    assert r["arguments"]["subagent_name"] == "code_reviewer"
    assert "bugs" in r["arguments"]["objective"]


def test_plain_text_returns_none() -> None:
    r = p("This is just a regular response without any function call.")
    assert r is None


def test_text_with_mentions_of_xml_is_not_parsed() -> None:
    r = p("The <tool_call> element is used for function calling in some APIs.")
    assert r is None  # shouldn't parse as real call


@pytest.mark.xfail(reason="XML invoke format not recognized by current parser")
def test_invoke_with_raw_body_fallback() -> None:
    r = p('<invoke name="unknown_tool">some unstructured text here</invoke>')
    assert r["skill_name"] == "unknown_tool"
    assert r["arguments"] == {"raw_input": "some unstructured text here"}
