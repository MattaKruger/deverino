# Report 4: Workflow Orchestration & Task Decomposition

**Generated:** 2026-06-20 | **Sources:** arXiv

---

## Task Decomposition for Coding Agents

### 1. "Runtime-Structured Task Decomposition for Agentic Coding Systems"
> **Shubhi Asthana, Bing Zhang, Chad DeLuca et al. (5 authors)** — arXiv:2605.15425 (2026-05-14)

Agentic coding systems increasingly use LLMs for software engineering tasks such as debugging, root cause analysis, and code review. However, many existing systems **encode task decomposition statically**, limiting flexibility. Proposes **runtime-structured** task decomposition.

**Relevance to Deverino:** Deverino's YAML workflow definitions are static task decomposition. This paper suggests runtime-dynamic decomposition would be more powerful — let the agent restructure tasks based on intermediate results.

---

### 2. "A Plan Reuse Mechanism for LLM-Driven Agent"
> **Guopeng Li, Ruiqi Wu, Haisheng Tan** — arXiv:2512.21309 (2025-12-24)

Integrating LLMs into personal assistants enhances their ability to solve complex tasks. Proposes a **plan reuse mechanism** — agents store and retrieve successful plans rather than re-deriving them each time.

**Relevance to Deverino:** Deverino's workflow YAML files are reusable plans. The paper provides formal grounding for plan caching and retrieval, which could improve workflow discovery.

---

## Harness Optimization & Evolution

### 3. "Evolving Agents in the Dark: Retrospective Harness Optimization via Self-Preference"
> **Wenbo Pan, Shujie Liu, Chin-Yew Lin et al. (8 authors)** — arXiv:2606.05922 (2026-06-04)

AI agents rely on a **harness of skills, tools, and workflows** to solve complex problems. Continually improving this harness is essential for adapting to new tasks. Existing optimization methods require ground-truth labels. Proposes **self-preference** optimization without labels.

**Relevance to Deverino:** This is directly about evolving the harness itself — skills, tools, and workflows — over time. Deverino's changelog and state tracking could feed into harness self-improvement.

---

### 4. "Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses"
> **Jiahang Lin, Shichun Liu, Chengjun Pan et al. (11 authors)** — arXiv:2604.25850 (2026-04-28)

Harnesses are now central to coding-agent performance, mediating how models interact with tools and execution environments. Yet **harness engineering remains a manual craft**. Proposes observability-driven automatic evolution.

**Relevance to Deverino:** **This paper is directly about Deverino's core problem.** Deverino is building an agentic harness; this paper describes how to make that harness self-improving through observability. Key insight: instrument the harness to collect metrics, then use those metrics to drive automatic improvements.

---

### 5. "AutoHarness: improving LLM agents by automatically synthesizing a code harness"
> **Xinghua Lou, Miguel Lázaro-Gredilla, Antoine Dedieu et al. (6 authors)** — arXiv:2603.03329 (2026-02-10)

Despite significant strides in LLMs, when used as agents, models often try to perform actions that are **not just suboptimal but strictly prohibited** for a given state. AutoHarness automatically synthesizes a code harness that constrains the agent to valid actions.

**Relevance to Deverino:** Deverino's harness should constrain agents to valid states/actions. AutoHarness provides patterns for automatic constraint synthesis — generating guard code from state specifications.

---

## Software Delegation

### 6. "Software Delegation Contracts: Measuring Reviewability in AI Coding-Agent Work"
> **Vincent Schmalbach** — arXiv:2606.17099 (2026-06-14)

AI coding agents increasingly accept assigned software tasks, modify repositories under bounded authority, and return work packages for review. Proposes **software delegation contracts** to measure reviewability.

**Relevance to Deverino:** When Deverino delegates tasks to sub-agents, the delegation contract pattern ensures the output is reviewable. Defines what metadata should accompany agent-produced work.

---

## Multi-Agent Workflows

### 7. "Morescient GAI for Software Engineering (Extended Version)"
> **Marcus Kessel, Colin Atkinson** — arXiv:2406.04710 (2024-06-07)

GAI technology promises to revolutionize SE through automatic checking, synthesis, and modification of SE artifacts. Proposes a framework for making GAI "morescient" — more knowledgeable about the software it operates on.

**Relevance to Deverino:** The concept of making AI "morescient" about a codebase aligns with Deverino's blackboard approach — maintaining contextual knowledge about the project being worked on.

---

## Key Takeaways for Deverino

1. **Static workflows → runtime decomposition** — YAML workflows should be starting points, not rigid plans
2. **Plan reuse** — successful workflows should be cached and retrievable
3. **Harness self-evolution** is the next frontier — use observability to drive automatic improvements
4. **Constraint synthesis** — auto-generate guards from state specs to prevent invalid actions
5. **Delegation contracts** — formalize what agent-produced work packages must include for reviewability
