# Skill Permission Enforcement — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Enforce the `permissions` field declared in every skill's SKILL.md frontmatter at the `SkillContext` and infrastructure level, so skills can't exceed their declared capabilities.

**Architecture:** Parse permissions from SKILL.md during skill discovery, thread a `SkillPermissions` dataclass into `SkillContext`. The context exposes `project_root` as read-only and a new `scratch_dir` as the only writable path. `BlackboardDatabase` access is gated by a thin `BlackboardAccessProxy`. Container mounts are split: project read-only, scratch read-write.

**Tech Stack:** Python 3.12, Pydantic (for permission model), existing `SkillContext`, `SkillRunner`, `container_spawn`, `BlackboardDatabase`

**Problem recap:** `execute_python` declares `auto_invokable: true` + `permissions: {blackboard: read_write, workspace: read_write}`. The LLM called it to create a new skill by writing `SKILL.md` + `skill.py` into `skills/`. The container has the full project root mounted read-write. Nothing enforced the declared permissions.

---

## Current Permission Declarations (ground truth)

```
consolidate_state         auto=False  blackboard=read_write  workspace=none
container_destroy         auto=False  blackboard=read_write  workspace=none
container_exec            auto=False  blackboard=none        workspace=none
container_spawn           auto=False  blackboard=read_write  workspace=read
delegate_task             auto=False  blackboard=read_write  workspace=none
evaluate_goal             auto=False  blackboard=none        workspace=none
execute_python            auto=True   blackboard=read_write  workspace=read_write  ← PROBLEM
read_memory               auto=True   blackboard=read        workspace=none
reflect_on_result         auto=False  blackboard=read_write  workspace=none
review_work               auto=True   blackboard=read_write  workspace=none
semble_search             auto=True   blackboard=none        workspace=read
spec_writer               auto=False  blackboard=read_write  workspace=read_write  ← also r/w
summarize_memory          auto=True   blackboard=none        workspace=none
web_search                auto=True   blackboard=none        workspace=none
```

**Protected directories** (no write access regardless of permissions): `skills/`, `harness_poc/system_skills/`, `harness.yaml`, `.env`, `harness_poc/blackboard.db`, `pyproject.toml`, `uv.lock`

---

### Task 1: Define `SkillPermissions` dataclass

**Objective:** Create a Pydantic model that validates and represents skill permissions.

**Files:**
- Create: `harness_poc/core/permissions.py`

**Step 1: Write the dataclass**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BlackboardPermission = Literal["read", "read_write", "none"]
WorkspacePermission = Literal["read", "read_write", "none"]

BLACKBOARD_VALUES = {"read", "read_write", "none"}
WORKSPACE_VALUES = {"read", "read_write", "none"}

# Directories that no skill may write to, regardless of workspace permission
PROTECTED_DIRS: tuple[str, ...] = (
    "skills",
    "harness_poc/system_skills",
    "harness_poc/system_prompts",
    ".env",
    "harness.yaml",
    "harness_poc/blackboard.db",
    "pyproject.toml",
    "uv.lock",
)


@dataclass(frozen=True, slots=True)
class SkillPermissions:
    blackboard: BlackboardPermission = "none"
    workspace: WorkspacePermission = "none"

    @classmethod
    def from_yaml(cls, raw: dict[str, str] | None) -> SkillPermissions:
        """Parse from SKILL.md frontmatter permissions dict. Invalid values → defaults."""
        if not isinstance(raw, dict):
            return cls()
        bb = raw.get("blackboard", "none")
        ws = raw.get("workspace", "none")
        return cls(
            blackboard=bb if bb in BLACKBOARD_VALUES else "none",
            workspace=ws if ws in WORKSPACE_VALUES else "none",
        )

    @property
    def can_read_blackboard(self) -> bool:
        return self.blackboard in ("read", "read_write")

    @property
    def can_write_blackboard(self) -> bool:
        return self.blackboard == "read_write"

    @property
    def can_read_workspace(self) -> bool:
        return self.workspace in ("read", "read_write")

    @property
    def can_write_workspace(self) -> bool:
        return self.workspace == "read_write"
```

**Step 2: Write tests**

Create `tests/test_permissions.py`:

```python
from harness_poc.core.permissions import SkillPermissions

def test_default_permissions_are_none():
    p = SkillPermissions()
    assert p.blackboard == "none"
    assert p.workspace == "none"
    assert not p.can_read_blackboard
    assert not p.can_write_blackboard

def test_from_yaml_reads_valid_values():
    p = SkillPermissions.from_yaml({"blackboard": "read", "workspace": "read_write"})
    assert p.blackboard == "read"
    assert p.workspace == "read_write"
    assert p.can_read_blackboard
    assert not p.can_write_blackboard
    assert p.can_read_workspace
    assert p.can_write_workspace

def test_from_yaml_rejects_invalid_values():
    p = SkillPermissions.from_yaml({"blackboard": "admin", "workspace": "full"})
    assert p.blackboard == "none"
    assert p.workspace == "none"

def test_from_yaml_handles_none():
    p = SkillPermissions.from_yaml(None)
    assert p.blackboard == "none"

def test_read_write_implies_read():
    p = SkillPermissions(blackboard="read_write", workspace="read_write")
    assert p.can_read_blackboard
    assert p.can_read_workspace
```

Run: `uv run pytest tests/test_permissions.py -v` — expect 5 passed.

**Step 3: Commit**

```bash
git add harness_poc/core/permissions.py tests/test_permissions.py
git commit -m "feat: add SkillPermissions dataclass with from_yaml parsing"
```

---

### Task 2: Parse permissions during skill discovery

**Objective:** `SkillRunner.parse_skill_document` already parses frontmatter. Add `permissions` to the parsed `SkillDocument` metadata.

**Files:**
- Modify: `harness_poc/core/skill_runner.py:224-277`

**Step 1: Update `SkillMetadata` TypedDict**

Add `permissions` field at `skill_runner.py:23-28`:

```python
class SkillMetadata(TypedDict):
    name: str
    description: str
    parameters: dict[str, Any]
    auto_invokable: bool
    permissions: dict[str, str]  # ADD
```

**Step 2: Parse permissions in `parse_skill_document`**

In the return dict at line ~264, add permissions extraction. After the `auto_invokable` line (247), add:

```python
        # Already exists at line 247:
        auto_invokable = bool(frontmatter.get("auto_invokable", False))
        # ADD after:
        raw_permissions = frontmatter.get("permissions", {})
        permissions = raw_permissions if isinstance(raw_permissions, dict) else {}
```

Then in the return dict at line ~269:

```python
        return {
            "metadata": {
                "name": name,
                "description": description,
                "parameters": cast("dict[str, Any]", parameters),
                "auto_invokable": auto_invokable,
                "permissions": cast("dict[str, str]", permissions),  # ADD
            },
            "body": body,
            "path": skill_file,
            "entrypoint": {
                "module": entrypoint_module,
                "function": entrypoint_function,
            },
        }
```

**Step 3: Pass permissions through `discover_skills`**

In the tools list (line ~68-78), add `permissions` to the function dict:

```python
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": skill_name,
                            "description": skill["metadata"]["description"],
                            "parameters": skill["metadata"]["parameters"],
                            "auto_invokable": skill["metadata"]["auto_invokable"],
                            "permissions": skill["metadata"]["permissions"],  # ADD
                        },
                    },
                )
```

**Step 4: Write integration test**

Add to `tests/test_skill_runner.py` or similar:

```python
def test_skill_metadata_includes_permissions():
    """Verify that parse_skill_document returns permissions from frontmatter."""
    runner = SkillRunner(database=mock_db, config=mock_config)
    # Use execute_python's real SKILL.md for a round-trip test
    skill_file = Path("harness_poc/system_skills/execute_python/SKILL.md")
    doc = runner.parse_skill_document(skill_file)
    assert doc["metadata"]["permissions"] == {"blackboard": "read_write", "workspace": "read_write"}
```

Run: `uv run pytest tests/ -k "test_skill_metadata" -v`

**Step 5: Commit**

```bash
git add harness_poc/core/skill_runner.py tests/
git commit -m "feat: parse permissions from SKILL.md frontmatter during discovery"
```

---

### Task 3: Add `permissions` and `scratch_dir` to `SkillContext`

**Objective:** `SkillContext` receives parsed `SkillPermissions`, enforces read-only `project_root`, and provides a writable `scratch_dir`.

**Files:**
- Modify: `harness_poc/core/skill_context.py`
- Create: `tests/test_skill_context_permissions.py`

**Step 1: Update `SkillContext` dataclass**

```python
@dataclass(frozen=True, slots=True)
class SkillContext:
    session_id: str
    skill_name: str
    database: BlackboardDatabase
    config: HarnessConfig
    permissions: SkillPermissions = field(default_factory=SkillPermissions)  # NEW
    stream_text: Callable[[str], None] | None = None
    on_tool_event: Callable[[str], None] | None = None

    @property
    def project_root(self) -> Path:
        """Read-only view of the project directory."""
        if not self.permissions.can_read_workspace:
            raise PermissionError(
                f"Skill '{self.skill_name}' has workspace={self.permissions.workspace!r} "
                f"— cannot access project files."
            )
        return self.config.project_root

    @property
    def scratch_dir(self) -> Path:
        """Writable scratch directory. Only available with workspace=read_write."""
        if not self.permissions.can_write_workspace:
            raise PermissionError(
                f"Skill '{self.skill_name}' has workspace={self.permissions.workspace!r} "
                f"— cannot write files."
            )
        scratch = self.config.project_root / ".deverino-scratch" / self.session_id
        scratch.mkdir(parents=True, exist_ok=True)
        return scratch

    # ... rest unchanged
```

**Step 2: Write tests**

Create `tests/test_skill_context_permissions.py`:

```python
import pytest
from pathlib import Path
from harness_poc.core.skill_context import SkillContext
from harness_poc.core.permissions import SkillPermissions

def test_project_root_accessible_with_read_permission():
    ctx = SkillContext(
        session_id="s1", skill_name="test",
        database=mock_db, config=mock_config,
        permissions=SkillPermissions(workspace="read"),
    )
    assert isinstance(ctx.project_root, Path)

def test_project_root_raises_with_none_permission():
    ctx = SkillContext(
        session_id="s1", skill_name="test",
        database=mock_db, config=mock_config,
        permissions=SkillPermissions(workspace="none"),
    )
    with pytest.raises(PermissionError, match="cannot access project files"):
        _ = ctx.project_root

def test_scratch_dir_created_with_read_write():
    ctx = SkillContext(
        session_id="s1", skill_name="test",
        database=mock_db, config=mock_config_tempdir,
        permissions=SkillPermissions(workspace="read_write"),
    )
    scratch = ctx.scratch_dir
    assert scratch.exists()
    assert scratch.is_dir()

def test_scratch_dir_raises_with_read_only():
    ctx = SkillContext(
        session_id="s1", skill_name="test",
        database=mock_db, config=mock_config,
        permissions=SkillPermissions(workspace="read"),
    )
    with pytest.raises(PermissionError, match="cannot write files"):
        _ = ctx.scratch_dir
```

Run: `uv run pytest tests/test_skill_context_permissions.py -v` — expect 4 passed.

**Step 3: Commit**

```bash
git add harness_poc/core/skill_context.py tests/test_skill_context_permissions.py
git commit -m "feat: add permissions enforcement to SkillContext (project_root, scratch_dir)"
```

---

### Task 4: Thread permissions from SkillRunner into SkillContext

**Objective:** `SkillRunner.execute_skill` parses the skill's permissions and passes `SkillPermissions` into the `SkillContext` constructor.

**Files:**
- Modify: `harness_poc/core/skill_runner.py:98-131`

**Step 1: Parse permissions during execution**

In `execute_skill`, after parsing the skill document (`skill = self.parse_skill_document(skill_file)` at line 118), extract permissions:

```python
            # After line 118:
            skill = self.parse_skill_document(skill_file)

            # ADD: Parse permissions
            from harness_poc.core.permissions import SkillPermissions
            skill_permissions = SkillPermissions.from_yaml(
                skill["metadata"].get("permissions", {})
            )
```

**Step 2: Pass permissions to SkillContext**

At the SkillContext construction (line ~121), add the `permissions` field:

```python
            context = SkillContext(
                session_id=session_id,
                skill_name=resolved_tool_name,
                database=self.database,
                config=self.config,
                permissions=skill_permissions,  # ADD
                stream_text=on_text,
                on_tool_event=on_tool_event,
            )
```

**Step 3: Update existing tests**

Any test that constructs a `SkillContext` directly now needs a `permissions` parameter. Since we gave it a default (`field(default_factory=SkillPermissions)`), existing tests that use `SkillContext(...)` without `permissions=` will default to `none` for everything. This is safe (conservative default) but may break tests that expect `project_root` to be accessible.

Run the full test suite to see what breaks:

```bash
uv run pytest -x --tb=short
```

Fix any broken tests by adding `permissions=SkillPermissions(workspace="read")` where needed.

**Step 4: Commit**

```bash
git add harness_poc/core/skill_runner.py tests/
git commit -m "feat: thread SkillPermissions from discovery through to SkillContext"
```

---

### Task 5: Add `BlackboardAccessProxy` for database-level enforcement

**Objective:** Wrap `BlackboardDatabase` with permission checks so skills with `blackboard: read` can't call `write_memory()`.

**Files:**
- Create: `harness_poc/core/blackboard_proxy.py`
- Modify: `harness_poc/core/skill_context.py`
- Create: `tests/test_blackboard_proxy.py`

**Step 1: Write the proxy**

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness_poc.core.permissions import SkillPermissions

if TYPE_CHECKING:
    from harness_poc.core.database import BlackboardDatabase
    from harness_poc.core.state import StatePayload, StateProposal


class BlackboardAccessProxy:
    """Wraps BlackboardDatabase and enforces skill permissions at method level."""

    def __init__(self, db: BlackboardDatabase, permissions: SkillPermissions) -> None:
        self._db = db
        self._permissions = permissions

    def _require_read(self) -> None:
        if not self._permissions.can_read_blackboard:
            raise PermissionError(
                f"Skill has blackboard={self._permissions.blackboard!r} — cannot read."
            )

    def _require_write(self) -> None:
        if not self._permissions.can_write_blackboard:
            raise PermissionError(
                f"Skill has blackboard={self._permissions.blackboard!r} — cannot write."
            )

    # --- Read methods (allowed with "read" or "read_write") ---

    def read_memory(self, session_id: str, memory_key: str) -> str | None:
        self._require_read()
        return self._db.read_memory(session_id, memory_key)

    def read_session_state(self, session_id: str) -> dict[str, Any]:
        self._require_read()
        return self._db.read_session_state(session_id)

    def read_project_state(self) -> dict[str, Any]:
        self._require_read()
        return self._db.read_project_state(session_id=None)  # adjust per actual API

    # --- Write methods (allowed only with "read_write") ---

    def write_memory(self, session_id: str, memory_key: str, data: Any) -> None:
        self._require_write()
        self._db.write_memory(session_id, memory_key, data)

    def append_session_state(self, session_id: str, payload: Any) -> None:
        self._require_write()
        self._db.append_session_state(session_id, payload)

    def create_state_proposal(self, *args: Any, **kwargs: Any) -> Any:
        self._require_write()
        return self._db.create_state_proposal(*args, **kwargs)

    # ... mirror any other write methods used by skills
```

Note: This needs to mirror the actual `BlackboardDatabase` API surface that skills use. Audit `read_memory`, `semble_search`, `consolidate_state`, `spec_writer`, `delegate_task`, `execute_python` to see which DB methods they call.

**Step 2: Wire proxy into SkillContext**

In `SkillContext.__post_init__` or constructor, wrap the database:

```python
    def __post_init__(self) -> None:
        if not isinstance(self.database, BlackboardAccessProxy):
            object.__setattr__(
                self, "database",
                BlackboardAccessProxy(self.database, self.permissions),
            )
```

Alternatively, in `SkillRunner.execute_skill`, wrap before constructing SkillContext.

**Step 3: Write tests**

```python
def test_proxy_blocks_write_with_read_permission():
    db = mock_db()
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))
    with pytest.raises(PermissionError):
        proxy.write_memory("s1", "key", "value")

def test_proxy_allows_read_with_read_permission():
    db = mock_db()
    db.write_memory("s1", "key", "value")
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read"))
    result = proxy.read_memory("s1", "key")
    assert result == "value"

def test_proxy_allows_write_with_read_write_permission():
    db = mock_db()
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="read_write"))
    proxy.write_memory("s1", "key", "value")  # should not raise

def test_proxy_blocks_all_with_none_permission():
    db = mock_db()
    proxy = BlackboardAccessProxy(db, SkillPermissions(blackboard="none"))
    with pytest.raises(PermissionError):
        proxy.read_memory("s1", "key")
```

Run: `uv run pytest tests/test_blackboard_proxy.py -v`

**Step 4: Commit**

```bash
git add harness_poc/core/blackboard_proxy.py harness_poc/core/skill_context.py tests/test_blackboard_proxy.py
git commit -m "feat: add BlackboardAccessProxy enforcing blackboard read/write permissions"
```

---

### Task 6: Split container mounts (project read-only, scratch read-write)

**Objective:** `container_spawn` mounts the project as read-only and adds a writable scratch volume. `execute_python` can read project files but writes only go to scratch.

**Files:**
- Modify: `harness_poc/system_skills/container_spawn/skill.py`
- Modify: `harness_poc/system_skills/execute_python/skill.py`

**Step 1: Change container_spawn mount**

In `container_spawn/skill.py` line ~65-77, split the mount:

```python
    project_root = str(ctx.project_root.resolve())
    scratch = str(ctx.scratch_dir.resolve()) if _wants_scratch(ctx) else None

    create_cmd: list[str] = [
        backend,
        "run",
        "-d",
        "--name",
        container_name,
        "-v",
        f"{project_root}:/workspace:ro",  # read-only
        "-w",
        "/workspace",
    ]
    if scratch:
        create_cmd.extend(["-v", f"{scratch}:/workspace/tmp"])  # writable scratch
    create_cmd.append(image)
    create_cmd.extend(KEEPALIVE_CMD)
```

Add helper:

```python
def _wants_scratch(ctx: SkillContext) -> bool:
    """Check if the calling skill needs write access."""
    return ctx.permissions.can_write_workspace
```

**Step 2: Update execute_python to use /workspace/tmp for writes**

The `execute_python` skill's description/behavior already says "scratchpad analysis." No code changes needed in `execute_python/skill.py` itself — the container mount restriction handles it. But update the SKILL.md body to document that `/workspace` is read-only and `/workspace/tmp` is the writable scratch area.

**Step 3: Update execute_python SKILL.md**

Add to the Behavior section:

```
4. Writes to /workspace (project files) are blocked by the read-only mount.
   Use /workspace/tmp for scratch files.
```

**Step 4: Write integration test**

The container tests may already exist. Add a test that verifies the mount is read-only:

```python
def test_execute_python_cannot_write_to_project():
    """execute_python with workspace=read_write should not be able to write to skills/."""
    result = execute_python(ctx_with_rw, {
        "code": "open('/workspace/skills/test_skill/SKILL.md', 'w').write('bad')",
    })
    assert result.status == "failed"
    assert "Permission denied" in result.content or "Read-only" in result.content
```

Note: This test requires a running container backend (podman/docker). If no backend is available, skip.

**Step 5: Commit**

```bash
git add harness_poc/system_skills/container_spawn/skill.py
git add harness_poc/system_skills/execute_python/SKILL.md
git add tests/
git commit -m "feat: split container mounts — project read-only, scratch read-write"
```

---

### Task 7: Add `scratch_dir` cleanup to `container_destroy`

**Objective:** When a session container is destroyed, clean up the scratch directory.

**Files:**
- Modify: `harness_poc/system_skills/container_destroy/skill.py`

**Step 1: Add scratch cleanup**

After destroying the container, remove the session's scratch directory:

```python
import shutil

# After successful container removal:
scratch = ctx.config.project_root / ".deverino-scratch" / ctx.session_id
if scratch.exists():
    shutil.rmtree(scratch, ignore_errors=True)
```

**Step 2: Commit**

```bash
git add harness_poc/system_skills/container_destroy/skill.py
git commit -m "feat: cleanup scratch dir when container is destroyed"
```

---

### Task 8: Add `allowed_skills` filtering for TUI/CLI goal runner

**Objective:** Use the existing `allowed_skills` pattern (from `pipeline_runner`) to scope which auto-invokable skills the agent sees in TUI/CLI mode. Exclude `execute_python` by default.

**Files:**
- Modify: `harness_poc/core/pydantic_runtime.py` (or `app_factory.py`)

**Step 1: Add `allowed_skills` parameter to runtime builder**

In `build_primary_agent` (or `build_skill_tools`), add an optional allowlist:

```python
def build_skill_tools(
    skill_runner: SkillRunner,
    allowed_skills: set[str] | None = None,
) -> list[Tool[AgentDeps]]:
    tools: list[Tool[AgentDeps]] = []
    for discovered_skill in skill_runner.discover_skills():
        function = discovered_skill.get("function", {})
        name = function.get("name")
        # ... existing checks ...
        if allowed_skills is not None and name not in allowed_skills:
            continue  # skip this tool
        # ... register tool ...
```

**Step 2: Configure default allowed set**

In `app_factory.py`, when building the runtime for TUI mode:

```python
# All auto-invokable skills EXCEPT those that can mutate the project
TUI_DEFAULT_ALLOWED = {
    "web_search",
    "semble_search",
    "read_memory",
    "summarize_memory",
    "review_work",
    # execute_python intentionally excluded — user can invoke via /skill
}
```

**Step 3: Commit**

```bash
git add harness_poc/core/pydantic_runtime.py harness_poc/app_factory.py
git commit -m "feat: add allowed_skills filtering for TUI goal runner context"
```

---

### Task 9: Run full test suite, fix regressions

**Objective:** Ensure all 184 existing tests pass with the new permission enforcement.

**Files:**
- Any that break

**Step 1: Run full suite**

```bash
uv run pytest -x --tb=short
```

Likely breakage points:
- Tests that construct `SkillContext` without permissions → default to `none`, `project_root` raises
- Container tests that expect read-write project mount
- Tests that call `write_memory` through a proxy with `read` permission

**Step 2: Fix each failure**

For each failing test:
1. If it constructs a `SkillContext`, add appropriate `permissions=SkillPermissions(...)` 
2. If it exercises container mounts, update to expect read-only project + writable scratch
3. If it calls DB write methods, ensure it uses `read_write` permission

**Step 3: Commit after all pass**

```bash
uv run pytest  # verify 184+ pass
git add -A
git commit -m "fix: update tests for permission enforcement"
```

---

### Task 10: Update `execute_python` SKILL.md description

**Objective:** Clarify what `execute_python` can and cannot do now that permissions are enforced.

**Files:**
- Modify: `harness_poc/system_skills/execute_python/SKILL.md`

**Step 1: Update description and behavior**

Change the description to:
```
description: >-
  Executes Python code inside a session-scoped container for scratchpad analysis,
  hypothesis testing, and data inspection. The project filesystem is read-only;
  write output to /workspace/tmp.
```

Add to Behavior section:
```
5. The project filesystem (/workspace) is mounted read-only.
   Write temporary files to /workspace/tmp.
6. Cannot create, modify, or delete files in skills/, harness_poc/, or
   any project source directory.
```

**Step 2: Commit**

```bash
git add harness_poc/system_skills/execute_python/SKILL.md
git commit -m "docs: clarify execute_python write restrictions in SKILL.md"
```

---

## Verification Checklist

After all tasks:

- [ ] `uv run pytest` — all 184+ tests pass
- [ ] `uv run ruff check .` — no new lint issues
- [ ] `uv run ty check` — no new type errors
- [ ] Manual: start TUI, agent CANNOT call `execute_python` autonomously
- [ ] Manual: `/skill execute_python {"code": "print(open('/workspace/skills/foo.md','w').write('x'))"}` — fails with PermissionError
- [ ] Manual: `/skill execute_python {"code": "open('/workspace/tmp/result.txt','w').write('hello')"}` — succeeds
- [ ] Manual: skills with `blackboard: none` (like `web_search`) can't call `read_memory`
- [ ] Manual: `spec_writer` (which legitimately writes to `specs/`) still works — needs `workspace: read_write` and the `specs/` directory must NOT be in PROTECTED_DIRS

---

## Design Decisions

1. **Protected directories are hardcoded, not in YAML.** These are structural invariants — no skill should ever write to `skills/` or `harness.yaml` regardless of what permissions say. Making it configurable invites misconfiguration.

2. **`workspace: read_write` means "can write to scratch only."** The original intent of `workspace: read_write` was ambiguous. We're formalizing it: read project files, write to scratch. If a skill genuinely needs to write to a specific project directory (like `spec_writer` writing to `specs/`), that directory must be excluded from PROTECTED_DIRS or the skill needs a different permission level in the future.

3. **Permission defaults are `none`.** If a SKILL.md doesn't declare permissions, the skill gets nothing. This is safe-by-default.

4. **`BlackboardAccessProxy` mirrors the actual API surface.** We're not building a generic proxy — we're explicitly exposing the methods skills actually use. This keeps the proxy auditable.

5. **Container mounts are read-only at the Docker/podman level.** Filesystem-level enforcement is stronger than in-process Python checks. Even if `execute_python` bypasses Python guards, the kernel won't let it write.
