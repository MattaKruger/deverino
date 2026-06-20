# Report 5: Safety, Reliability & Observability

**Generated:** 2026-06-20 | **Sources:** arXiv

---

## Enterprise Safety & Multi-Tenancy

### 1. "Securing the Agent: Vendor-Neutral, Multitenant Enterprise Retrieval and Tool Use"
> **Francisco Javier Arceo, Varsha Prasad Narsing** — arXiv:2605.05287 (2026-05-06)

RAG and agentic AI systems are increasingly prevalent in enterprise AI deployments. Real enterprise environments introduce challenges largely absent from academic settings: **multi-tenancy, data isolation, access control, vendor neutrality**.

**Relevance to Deverino:** If Deverino ever supports multi-project or multi-user deployments, this paper's patterns for tenant isolation and access control are essential reading.

---

## Deterministic Replay & Audit

### 2. "Replayable Financial Agents: A Determinism-Faithfulness Assurance Harness for Tool-Using LLM Agents"
> **Raffi Khatchadourian** — arXiv:2601.15322 (2026-01-17)

LLM agents struggle with regulatory audit replay. When asked to reproduce a flagged transaction decision with identical inputs, many deployments fail to return consistent results. Introduces a **determinism-faithfulness assurance harness**.

**Relevance to Deverino:** The determinism-faithfulness concept extends beyond finance. Deverino's state changelog could be extended to support full replay of agent decision sequences for debugging and audit.

**Key patterns:**
- Log all tool inputs and outputs
- Log all LLM calls with parameters
- Replay by feeding logged outputs as mock responses
- Verify that replayed decisions match original decisions

---

## Observability-Driven Evolution

### 3. "Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses"
> **Jiahang Lin, Shichun Liu, Chengjun Pan et al. (11 authors)** — arXiv:2604.25850 (2026-04-28)

Harness engineering remains a manual craft because automating it faces challenges in evaluation, optimization, and generalization. Proposes **observability-driven automatic evolution**: instrument the harness, collect metrics, drive improvements.

**Relevance to Deverino:** This paper defines what metrics a harness should collect and how to use them for self-improvement. Directly actionable for Deverino's observability strategy.

**Suggested metrics:**
- Task completion rate
- Tool call success rate
- Token efficiency (tokens per task)
- Hallucination rate (invalid actions attempted)
- Recovery rate (errors successfully handled)

---

## Over-Privilege & Least Privilege

### 4. "When Lower Privileges Suffice: Investigating Over-Privileged Tool Selection in LLM Agents"
> **Kaiyue Yang, Yuyan Bu, Jingwei Yi et al. (8 authors)** — arXiv:2606.20023 (2026-06-18)

Agents select tools autonomously. This paper investigates whether agents select **over-privileged tools** when lower-privilege alternatives exist. The answer is often yes — agents don't naturally respect least-privilege principles.

**Relevance to Deverino:** Skills in Deverino should declare privilege requirements. The harness should enforce that an agent only receives tools matching the task's privilege needs, not all available tools.

---

## Safety Evaluation of Orchestration

### 5. "AgentGuard: Repurposing Agentic Orchestrator for Safety Evaluation of Tool Orchestration"
> **Jizhou Chen, Samuel Lee Cong** — arXiv:2502.09809 (2025-02-13)

Tool use integration into LLMs enables agentic systems with real-world impact. Unlike standalone LLMs, **compromised agents can execute malicious workflows** through tool orchestration. AgentGuard evaluates orchestration safety before execution.

**Relevance to Deverino:** Deverino's workflow runtime should include a safety evaluation pass before executing workflows — checking for dangerous tool combinations, privilege escalation, or data exfiltration patterns.

---

## Software Delegation Reviewability

### 6. "Software Delegation Contracts: Measuring Reviewability in AI Coding-Agent Work"
> **Vincent Schmalbach** — arXiv:2606.17099 (2026-06-14)

Proposes measuring **reviewability** of AI coding-agent work through delegation contracts — explicit agreements about what the agent will deliver, how it will be structured, and what evidence accompanies the work.

**Relevance to Deverino:** Each sub-agent delegation in Deverino should produce a reviewable work package with:
- What was requested
- What was delivered
- Evidence of correctness (tests passed, lint clean)
- A diff summary
- Confidence assessment

---

## Key Takeaways for Deverino

1. **Multi-tenancy** — plan for data isolation from the start if multi-project support is desired
2. **Deterministic replay** — log all tool calls and LLM interactions for audit/debug
3. **Observability metrics** — instrument the harness to collect the metrics that drive self-improvement
4. **Least-privilege tool selection** — don't give agents all tools; match tools to task privilege
5. **Workflow safety evaluation** — check for dangerous combinations before execution
6. **Delegation contracts** — formalize what sub-agent output must include for reviewability
