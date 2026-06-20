"""orchestrate — Dynamic decomposer + parallel worker coordinator.

Key difference from pipeline YAML: subtasks are *discovered* by the
orchestrator at runtime based on the specific input, not predefined.

Now executes subtasks directly via delegate_task's _run_subagent,
collecting results and synthesizing them into a unified output.

Decomposition is LLM-driven with keyword-based fallback.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, Field

from harness_poc.core.skills import SkillContext, SkillResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured output for LLM-driven decomposition
# ---------------------------------------------------------------------------


class SubTaskSpec(BaseModel):
    """A single subtask produced by the decomposition LLM."""

    id: str = Field(description="Short snake_case identifier, e.g. 'analyze' or 'search_sources'")
    role: str = Field(description="Role name for the worker agent, e.g. 'architect'")
    description: str = Field(description="One-sentence description of what this subtask does")
    input: str = Field(description="Detailed instructions for the worker agent")


class DecompositionPlan(BaseModel):
    """LLM-produced decomposition of an objective into subtasks."""

    subtasks: list[SubTaskSpec] = Field(
        description="2-5 independent subtasks that cover the objective",
        min_length=1,
        max_length=8,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def execute(ctx: SkillContext, arguments: dict[str, Any]) -> SkillResult:
    """Decompose, delegate in parallel, and synthesize.

    Args:
        objective: The high-level goal.
        available_roles: List of role names available for workers.
        max_parallel: Max concurrent subtasks (default 3).
        context: Optional additional context.
    """
    objective = str(arguments.get("objective", ""))
    available_roles = arguments.get("available_roles", [])
    if isinstance(available_roles, str):
        available_roles = [r.strip() for r in available_roles.split(",")]
    max_parallel = int(arguments.get("max_parallel", 3))
    extra_context = str(arguments.get("context", ""))

    if not objective:
        return SkillResult(status="failed", content="Missing required argument: objective.")

    # 1. Decompose the objective into subtasks (LLM-driven with fallback)
    subtasks = _llm_decompose(ctx, objective, available_roles, extra_context)
    ctx.emit_text(
        f"Decomposed into {len(subtasks)} subtasks: {', '.join(s['id'] for s in subtasks)}"
    )

    # 2. Execute subtasks via delegate_task's sub-agent runner, possibly in parallel
    from harness_poc.system_skills.delegate_task.skill import _run_subagent

    subtask_results: list[dict[str, Any]] = []

    def _run_one(subtask: dict[str, Any]) -> dict[str, Any]:
        """Execute one subtask via delegate_task's sub-agent."""
        role = subtask["role"]
        try:
            persona_template = ctx.read_subagent_template(role)
        except Exception:
            # Fallback: build a minimal persona from role name
            persona_template = (
                f"You are a {role} agent. Complete the assigned objective "
                f"thoroughly and return a structured result."
            )

        output = _run_subagent(
            persona_name=role,
            persona_template=persona_template,
            objective=subtask["description"],
            context=subtask.get("input", ""),
            llm_config=ctx.config.llm,
            agents_dir=ctx.config.project_root / "subagents",
        )
        return {
            "subtask_id": subtask["id"],
            "role": role,
            "status": output.status,
            "content": output.summary,
            "artifacts": output.artifacts,
        }

    if max_parallel > 1 and len(subtasks) > 1:
        with ThreadPoolExecutor(max_workers=min(max_parallel, len(subtasks))) as pool:
            futures = {pool.submit(_run_one, s): s for s in subtasks}
            for future in as_completed(futures):
                try:
                    subtask_results.append(future.result())
                except Exception as exc:
                    failed = futures[future]
                    subtask_results.append(
                        {
                            "subtask_id": failed["id"],
                            "role": failed.get("role", "unknown"),
                            "status": "failed",
                            "content": f"Subtask failed: {exc}",
                            "artifacts": {},
                        }
                    )
    else:
        for subtask in subtasks:
            subtask_results.append(_run_one(subtask))

    # 3. Synthesize results
    synthesis = synthesize(subtask_results)
    ctx.emit_text(
        f"Synthesis complete: {len(subtask_results)} subtasks processed. "
        f"Conflicts: {len(synthesis.get('conflicts', []))}, "
        f"Gaps: {len(synthesis.get('gaps', []))}"
    )

    # 4. Store delegation tree in shared memory
    try:
        ctx.database.write_memory(
            ctx.session_id,
            "orchestration_tree",
            {
                "objective": objective,
                "delegation_tree": synthesis.get("delegation_tree", {}),
                "subtask_results": [
                    {
                        "id": r["subtask_id"],
                        "role": r.get("role", ""),
                        "status": r.get("status", ""),
                    }
                    for r in subtask_results
                ],
            },
        )
    except Exception:
        pass  # Non-critical — dashboard reads from events, not memory

    return SkillResult(
        status="success",
        content=synthesis.get("synthesis", ""),
        artifacts={
            "synthesis": synthesis.get("synthesis", ""),
            "conflicts": synthesis.get("conflicts", []),
            "gaps": synthesis.get("gaps", []),
            "subtask_count": len(subtask_results),
            "delegation_tree": synthesis.get("delegation_tree", {}),
            "subtask_results": subtask_results,
        },
    )


def synthesize(subtask_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Synthesize results from multiple worker agents.

    Identifies conflicts, gaps, and produces a unified result with
    traceability to which subtask produced what.
    """
    conflicts: list[str] = []
    gaps: list[str] = []
    combined: list[str] = []

    for i, result in enumerate(subtask_results):
        subtask_id = result.get("subtask_id", f"subtask-{i}")
        content = result.get("content", "") or result.get("summary", "")
        status = result.get("status", "unknown")

        combined.append(f"## {subtask_id} ({status})\n{content}")

        # Conflict detection: check for contradictory claims between subtasks
        for j, other in enumerate(subtask_results):
            if j <= i:
                continue
            other_id = other.get("subtask_id", f"subtask-{j}")
            other_content = other.get("content", "") or other.get("summary", "")
            conflict = _detect_conflict(content, other_content)
            if conflict:
                conflicts.append(f"Conflict between {subtask_id} and {other_id}: {conflict}")

    # Gap detection: check if any subtask produced empty/nil output
    for result in subtask_results:
        subtask_id = result.get("subtask_id", "unknown")
        content = result.get("content", "") or result.get("summary", "")
        if not content or len(str(content).strip()) < 10:
            gaps.append(f"Subtask {subtask_id} produced minimal output — may need retry.")

    return {
        "synthesis": "\n\n".join(combined),
        "conflicts": conflicts,
        "gaps": gaps,
        "subtask_count": len(subtask_results),
        "delegation_tree": {
            "subtasks": [
                {
                    "id": r.get("subtask_id", f"subtask-{i}"),
                    "role": r.get("role", "unknown"),
                    "status": r.get("status", "unknown"),
                    "output_length": len(str(r.get("content", ""))),
                }
                for i, r in enumerate(subtask_results)
            ]
        },
    }


def _llm_decompose(
    ctx: SkillContext,
    objective: str,
    roles: list[str],
    context: str,
) -> list[dict[str, Any]]:
    """Decompose using an LLM call, falling back to keyword-based.

    Loads role descriptions from agents/roles/ as context for the LLM,
    then asks the model to produce a DecompositionPlan.
    """
    role_descs = _load_role_descriptions(ctx, roles)

    try:
        from harness_poc.core.runtime import build_model
        from pydantic_ai import Agent

        model = build_model(ctx.config.llm)
        agent = Agent(
            model,
            output_type=DecompositionPlan,
            system_prompt=(
                "You are a task decomposition specialist. Given a high-level "
                "objective, break it into 2-5 independent subtasks that can "
                "run in parallel. Each subtask must have a unique id, an "
                "assigned role from the available list, a one-sentence "
                "description, and detailed input instructions for the worker. "
                "Subtasks should be self-contained with clear boundaries. "
                "Do not create subtasks that depend on each other's output."
            ),
            output_retries=1,
        )

        role_list = ", ".join(roles) if roles else "architect, code_reviewer"
        prompt = (
            f"Objective: {objective}\n\n"
            f"Available roles: {role_list}\n\n"
        )
        if role_descs:
            prompt += f"Role descriptions:\n{role_descs}\n\n"
        if context:
            prompt += f"Additional context: {context}\n\n"
        prompt += (
            "Decompose this objective into independent subtasks. "
            "Assign each to the most appropriate role."
        )

        result = agent.run_sync(prompt)
        plan = result.output
        if plan and plan.subtasks:
            logger.info(
                "LLM decomposition produced %d subtasks for: %s",
                len(plan.subtasks),
                objective[:80],
            )
            return [
                {
                    "id": st.id,
                    "role": st.role,
                    "description": st.description,
                    "input": st.input,
                }
                for st in plan.subtasks
            ]
    except Exception:
        logger.warning(
            "LLM decomposition failed, falling back to keyword-based",
            exc_info=True,
        )

    return _decompose(objective, roles, context)


def _load_role_descriptions(ctx: SkillContext, roles: list[str]) -> str:
    """Load role knowledge from agents/roles/ for LLM context."""
    parts: list[str] = []
    roles_dir = ctx.config.project_root / "agents" / "roles"
    if not roles_dir.exists():
        return ""

    target = set(roles) if roles else {"architect", "code_reviewer"}
    for role_name in sorted(target):
        skill_md = roles_dir / role_name / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
            parts_count = 0
            body_start = 0
            for i, line in enumerate(content.split("\n")):
                if line.strip() == "---":
                    parts_count += 1
                    if parts_count == 2:
                        body_start = i + 1
                        break
            body = "\n".join(content.split("\n")[body_start:]).strip()
            if body:
                parts.append(f"### {role_name}\n{body}")
        except Exception:
            pass

    return "\n\n".join(parts[:5])


def _decompose(objective: str, roles: list[str], context: str) -> list[dict[str, Any]]:
    """Decompose an objective into subtasks.

    Uses keyword matching for common patterns; falls back to a generic
    plan/execute decomposition. A future enhancement will replace this
    with an LLM-driven decomposition call.
    """
    obj_lower = objective.lower()
    subtasks: list[dict[str, Any]] = []
    role_idx = 0

    if any(kw in obj_lower for kw in ("refactor", "change", "modify", "edit")):
        subtasks.append(
            {
                "id": "analyze",
                "role": _pick_role(roles, role_idx, "architect"),
                "description": (
                    f"Analyze the current code and identify what needs to change: {objective}"
                ),
                "input": (
                    f"Analyze this codebase change: {objective}. "
                    "Identify affected files and dependencies."
                ),
            }
        )
        role_idx += 1
        subtasks.append(
            {
                "id": "implement",
                "role": _pick_role(roles, role_idx, "code_reviewer"),
                "description": f"Implement the changes: {objective}",
                "input": (f"Implement this change: {objective}. Write the code modifications."),
            }
        )
        role_idx += 1
        subtasks.append(
            {
                "id": "review",
                "role": _pick_role(roles, role_idx, "code_reviewer"),
                "description": f"Review the changes for correctness and safety: {objective}",
                "input": (
                    f"Review these changes for bugs, security issues, and style: {objective}."
                ),
            }
        )

    elif any(kw in obj_lower for kw in ("research", "search", "find", "investigate")):
        subtasks.append(
            {
                "id": "search",
                "role": _pick_role(roles, role_idx, "web_researcher"),
                "description": f"Search for relevant information: {objective}",
                "input": (f"Research task: {objective}. Find relevant sources and summarize."),
            }
        )
        role_idx += 1
        subtasks.append(
            {
                "id": "validate",
                "role": _pick_role(roles, role_idx, "data_validator"),
                "description": f"Validate and fact-check findings: {objective}",
                "input": (f"Validate the research findings for accuracy: {objective}."),
            }
        )
        role_idx += 1
        subtasks.append(
            {
                "id": "synthesize",
                "role": _pick_role(roles, role_idx, "architect"),
                "description": f"Synthesize findings into coherent report: {objective}",
                "input": (f"Synthesize all findings into a coherent answer: {objective}."),
            }
        )

    else:
        # Generic decomposition
        subtasks.append(
            {
                "id": "plan",
                "role": _pick_role(roles, 0, "architect"),
                "description": f"Plan the approach for: {objective}",
                "input": f"Plan the approach to accomplish: {objective}.",
            }
        )
        subtasks.append(
            {
                "id": "execute",
                "role": _pick_role(roles, 1, "code_reviewer"),
                "description": f"Execute the plan for: {objective}",
                "input": f"Execute the planned approach: {objective}.",
            }
        )

    return subtasks


def _pick_role(roles: list[str], idx: int, fallback: str) -> str:
    """Pick a role from the list, cycling through available ones."""
    if not roles:
        return fallback
    return roles[idx % len(roles)]


def _detect_conflict(a: str, b: str) -> str | None:
    """Simple conflict detection between two outputs."""
    a_lower = a.lower()
    b_lower = b.lower()

    contradictory_pairs = [
        ("must not", "must"),
        ("never", "always"),
        ("cannot", "can"),
        ("incorrect", "correct"),
        ("error", "success"),
    ]

    for neg, pos in contradictory_pairs:
        if neg in a_lower and pos in b_lower:
            return f"One output says '{neg}' while another implies '{pos}'"
        if neg in b_lower and pos in a_lower:
            return f"One output says '{neg}' while another implies '{pos}'"

    return None
