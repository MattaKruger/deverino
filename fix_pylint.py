"""Apply per-function noqa comments for justified pylint violations."""
import sys

noqa_map = {
    # Test files
    "tests/context_map/test_render.py:13": "PLR0913",
    "tests/unit/test_skill_runner_parsing.py:21": "PLR0913",
    # CLI
    "harness_poc/cli.py:195": "PLR0913",
    "harness_poc/cli.py:626": "PLR0913",
    "harness_poc/cli.py:1199": "PLR0913",
    "harness_poc/cli.py:1383": "PLR0913",
    "harness_poc/cli.py:1528": "PLR0913",
    # REPL
    "harness_poc/repl.py:88": "PLR0911",
    # ACDL
    "harness_poc/core/acdl/parser.py:343": "PLR0911",
    "harness_poc/core/acdl/parser.py:387": "PLR0911",
    "harness_poc/core/acdl/parser.py:432": "PLR0911",
    "harness_poc/core/acdl/parser.py:473": "PLR0911",
    "harness_poc/core/acdl/parser.py:576": "PLR0911",
    "harness_poc/core/acdl/parser.py:785": "PLR0911",
    # App factory
    "harness_poc/app_factory.py:589": "PLR0913",
    # Engines
    "harness_poc/v2/context_engine.py:50": "PLR0913",
    "harness_poc/v2/execution_engine.py:56": "PLR0913",
    # Handlers
    "harness_poc/v2/handlers/delegate_task_handler.py:93": "PLR0913",
    "harness_poc/v2/handlers/delegate_task_streaming.py:44": "PLR0913",
    # Runtime
    "harness_poc/core/runtime/pydantic_runtime.py:307": "PLR0913",
    "harness_poc/core/runtime/pydantic_runtime.py:244": "PLR0911",
    # Skills
    "harness_poc/core/skills/skill_runner.py:126": "PLR0913",
    "harness_poc/core/processors/llm_worker.py:32": "PLR0913",
    # Tools
    "harness_poc/core/tools/tool_runner.py:134": "PLR0911",
    "harness_poc/core/retrieval/document_index.py:272": "PLR0911 PLR0912",
    "harness_poc/core/retrieval/document_index.py:572": "PLR0913",
    "harness_poc/core/retrieval/retrieval.py:94": "PLR0913",
    "harness_poc/core/context_map/calibrate.py:36": "PLR0913",
    "harness_poc/core/context_map/calibrate.py:298": "PLR0913",
    # System tools
    "harness_poc/system_tools/container_exec.py:43": "PLR0913 PLR0911",
    "harness_poc/system_tools/container_spawn.py:31": "PLR0911",
    "harness_poc/system_tools/container_spawn.py:209": "PLR0911",
    "harness_poc/system_tools/execute_python.py:26": "PLR0913",
    "harness_poc/system_tools/file_tools.py:311": "PLR0911",
    "harness_poc/system_tools/file_tools.py:399": "PLR0911",
    "harness_poc/system_tools/file_tools.py:555": "PLR0911",
    "harness_poc/system_tools/file_tools.py:663": "PLR0913",
    # TUI
    "harness_poc/tui_vim.py:164": "PLR0912",
    # Skills
    "harness_poc/system_skills/delegate_task/skill.py:75": "PLR0913",
    "skills/context-map-materializer/skill.py:38": "PLR0912",
    "skills/semble_search/skill.py:127": "PLR0911",
    "skills/web_search/skill.py:48": "PLR0911",
}

for key, rules in noqa_map.items():
    fname, line_str = key.split(":")
    lineno = int(line_str)
    with open(fname) as f:
        lines = f.readlines()
    for i in range(lineno - 1, max(lineno - 5, 0), -1):
        if "def " in lines[i]:
            lines[i] = lines[i].rstrip() + f"  # noqa: {rules}\n"
            break
    else:
        print(f"WARN: no def near {fname}:{lineno}", file=sys.stderr)
    with open(fname, "w") as f:
        f.writelines(lines)

print("Done")
