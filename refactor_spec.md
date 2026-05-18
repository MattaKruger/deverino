# Refactoring Specification: LLM Agent Harness (V1 to V1.1)

## 1. Context & Objective

We are refactoring our Python-based LLM Agent Harness. The current Proof of Concept (POC) mixes the core engine's mechanical logic with user-defined project workflows.

**The Goal:** Architecturally split the application into **The Engine** (immutable system mechanics) and **The Workspace** (mutable, project-specific configuration and skills).

**Tech Stack:** Python 3.12+, `uv` (dependency management), `ruff` (linting/formatting), standard library `sqlite3`, `pyyaml`.

## 2. Target Directory Structure

Refactor the current codebase to perfectly match this tree:

```text
.
├── harness_poc/                  # THE ENGINE (Core Logic)
│   ├── core/
│   │   ├── database.py           # SQLite blackboard logic
│   │   ├── llm_client.py         # Mock API wrappers
│   │   └── skill_runner.py       # YAML frontmatter parser & tool executor
│   ├── system_skills/            # Built-in Engine Tools
│   │   ├── delegate_task/
│   │   │   └── SKILL.md          # Tool: Spawns sub-agent loops
│   │   └── read_memory/
│   │       └── SKILL.md          # Tool: Reads SQLite blackboard
│   ├── system_prompts/
│   │   └── SOUL.md               # Base engine persona & error handlers
│   └── main.py                   # Engine entrypoint
│
├── harness.yaml                  # THE WORKSPACE CONFIG (Defines paths)
├── skills/                       # PROJECT SKILLS (Domain-specific)
│   └── execute_podman/           # Example: user-defined project skill
│       └── SKILL.md
├── personas/                     # PROJECT AGENTS
│   ├── data_validator.md
│   └── web_researcher.md
└── workflows/                    # PROJECT EXECUTION GRAPHS
    └── default_workflow.yaml

3. Execution Phases
Phase 1: Directory Restructuring

    Rename harness_poc/skills/ to harness_poc/system_skills/.
    (Note: These are baseline system requirements, not user-configurable tasks. They get full read/write access to the database).

    Rename harness_poc/templates/ to harness_poc/system_prompts/ and move the main SOUL.md inside it.

    Create the empty Workspace directories at the project root: skills/, personas/, and workflows/.

Phase 2: Configuration Layer (harness.yaml)

Create or update harness.yaml at the project root to map these new directories.
YAML

version: 1.1

paths:
  # Engine Paths
  soul: harness_poc/system_prompts/SOUL.md
  system_skills: harness_poc/system_skills

  # Workspace Paths
  project_skills: skills
  personas: personas
  workflows: workflows

runtime:
  database_path: harness_poc/blackboard.db

Phase 3: Code Refactoring (harness_poc/core/skill_runner.py)

Update the SkillRunner class to be configuration-aware.

    Implement a method to parse harness.yaml on initialization.

    Update the discover_skills() method. It must now scan both paths.system_skills and paths.project_skills.

    It must combine the YAML frontmatter from both directories into a single JSON schema array to pass to the LLM.

    Update the execute_tool() routing logic to ensure delegate_task now reads template files from the paths.personas directory defined in the YAML.

Phase 4: Code Refactoring (harness_poc/main.py)

    Update main.py to read the harness.yaml file on startup.

    Load the system prompt from paths.soul.

    Pass the combined skill schemas (System + Project) to the LLMClient during the while True: execution loop.

4. Strict Constraints & Quality Rules

    Type Hinting: Maintain strict Python 3.12+ typing (typing module, | union operators, explicit return types).

    Idempotency: The database.py initialization must safely handle existing databases without throwing errors (CREATE TABLE IF NOT EXISTS).

    Tooling: Assume uv and ruff are running. Do not introduce massive external frameworks (like Langchain or LlamaIndex). Stick to the standard library + pyyaml.

    Imports: Ensure absolute/relative imports within harness_poc/ are updated to reflect the new structure.

5. Acceptance Criteria

The refactor is successful if:

    Running uv run ruff check . returns 0 errors.

    Running uv run python harness_poc/main.py successfully boots the loop.

    The LLM has access to both read_memory (System Skill) and any mock skill placed in the root skills/ directory.
```
