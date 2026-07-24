"""Scenario runner — drives the deverino harness through real entry points.

Calls build_app_state() (same as REPL startup) and handle_repl_input() (same as
user typing) for each step. No TestModel, no MagicMock — real LLM, real tools,
real system prompt assembly, real decorator, real DB.

Usage:
    uv run python scripts/scenario_runner.py <scenario.yaml>

Output: structured JSON to stdout.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from typing import Any

import yaml


def run_scenario(scenario_path: str) -> dict[str, Any]:
    """Run a scenario file through the real harness.

    Each scenario is a YAML file with:
        name: scenario_name
        config_overrides:  # optional, applied before build_app_state
          cartographer:
            cross_corpus:
              retrieval: semantic
        steps:
          - input: "/corpus-retrieval semantic"
            expect_stdout_contains: "Retrieval mode set to: semantic"
          - input: "how does auth work?"
            expect_stdout_contains: "auth"
            wait_seconds: 0  # optional, for materialization delays
          - input: "/state show session"
            expect_stdout_contains: "session"
        assertions:
          - type: db_query
            query: "retrieval_get_embeddings"
            corpus_key: "deverino:codebase"
            expect: "len > 0"
          - type: retrieval_mode
            expect: "semantic"
    """
    scenario = yaml.safe_load(Path(scenario_path).read_text())

    # Capture stdout to assert on output
    captured = StringIO()

    # Build real app state — same path as REPL startup
    from harness_poc.app_factory import build_app_state

    # Apply config overrides if specified
    overrides = scenario.get("config_overrides", {})
    if overrides:
        import os
        if "cartographer" in overrides:
            cc = overrides["cartographer"].get("cross_corpus", {})
            if "retrieval" in cc:
                os.environ["HARNESS_CORPUS_RETRIEVAL"] = cc["retrieval"]

    app_state = build_app_state()

    # Import the real REPL input handler
    from harness_poc.repl import handle_repl_input

    results = []
    for i, step in enumerate(scenario.get("steps", [])):
        user_input = step["input"]
        expect_contains = step.get("expect_stdout_contains")
        wait_seconds = step.get("wait_seconds", 0)

        if wait_seconds:
            import time
            time.sleep(wait_seconds)

        # Redirect stdout to capture REPL output
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            handle_repl_input(app_state, user_input)
        except Exception as exc:
            captured.write(f"[ERROR] {exc}\n")
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        captured.truncate(0)
        captured.seek(0)

        step_result = {
            "step": i + 1,
            "input": user_input,
            "output_preview": output[:500],
            "passed": True,
        }

        if expect_contains:
            found = expect_contains.lower() in output.lower()
            step_result["expect"] = expect_contains
            step_result["found"] = found
            step_result["passed"] = found

        results.append(step_result)

    # Run assertions
    assertion_results = []
    for assertion in scenario.get("assertions", []):
        atype = assertion["type"]
        ar: dict[str, Any] = {"type": atype, "passed": True}

        if atype == "retrieval_mode":
            mode = app_state.runtime.pydantic_runtime.deps.retrieval_mode[0]
            expected = assertion["expect"]
            ar["actual"] = mode
            ar["expected"] = expected
            ar["passed"] = mode == expected

        elif atype == "db_query":
            db = app_state.database
            if assertion["query"] == "retrieval_get_embeddings":
                ck = assertion.get("corpus_key", "deverino:codebase")
                embs = db.retrieval_get_embeddings(ck)
                ar["corpus_key"] = ck
                ar["embedding_count"] = len(embs)
                if assertion.get("expect") == "len > 0":
                    ar["passed"] = len(embs) > 0

            elif assertion["query"] == "get_all_corpus_keys":
                keys = db.get_all_corpus_keys()
                ar["corpora"] = keys
                if assertion.get("expect"):
                    ar["passed"] = eval(assertion["expect"], {"len": len, "keys": keys})

        elif atype == "system_prompt_contains":
            prompt = "\n\n".join(
                app_state.runtime.pydantic_runtime.agent._system_prompts  # noqa: SLF001
            )
            expected = assertion["expect"]
            ar["found"] = expected in prompt
            ar["passed"] = expected in prompt

        assertion_results.append(ar)

    total_steps = len(results)
    passed_steps = sum(1 for r in results if r["passed"])
    total_assertions = len(assertion_results)
    passed_assertions = sum(1 for a in assertion_results if a["passed"])

    return {
        "scenario": scenario.get("name", "unnamed"),
        "steps": results,
        "assertions": assertion_results,
        "summary": {
            "steps_total": total_steps,
            "steps_passed": passed_steps,
            "assertions_total": total_assertions,
            "assertions_passed": passed_assertions,
            "all_passed": passed_steps == total_steps and passed_assertions == total_assertions,
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: scenario_runner.py <scenario.yaml>"}))
        sys.exit(1)

    result = run_scenario(sys.argv[1])
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["summary"]["all_passed"] else 1)
