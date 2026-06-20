# Report 2: Skill Systems & Tool Integration

**Generated:** 2026-06-20 | **Sources:** arXiv

---

## Skill Specifications & Formats

### 1. "Toward User Comprehension Supports for LLM Agent Skill Specifications"
> **Zikai Alex Wen** — arXiv:2605.19362 (2026-05-19)

Studies how users interpret and select agent skills through their **SKILL markdown specifications**. Existing audits focus on malicious/unsafe skills. This paper studies comprehension: can users understand what a skill does from its SKILL.md?

**Relevance to Deverino:** Deverino uses `SKILL.md` files. This paper provides empirical data on how well users understand skill specs — directly applicable to skill authoring UX.

---

### 2. "SkCC: Portable and Secure Skill Compilation for Cross-Framework LLM Agents"
> **Yipeng Ouyang, Yi Xiao, Yuhao Gu et al. (4 authors)** — arXiv:2605.03353 (2026-05-05)

LLM agents increasingly rely on reusable skills (SKILL markdown files), but these artifacts **lack portability**: agent frameworks are highly sensitive to prompt formatting. Proposes SkCC for cross-framework skill compilation.

**Relevance to Deverino:** If Deverino wants skills to be portable across other agent frameworks, this is essential reading. Also relevant for security: compiled skills can be sandboxed.

---

### 3. "Skill Retrieval Augmentation for Agentic AI"
> **Weihang Su, Jianming Long, Qingyao Ai et al. (9 authors)** — arXiv:2604.24594 (2026-04-27)

As LLMs become agentic problem solvers, they increasingly rely on **external, reusable skills** beyond native parametric capabilities. Existing agent frameworks retrieve skills naively. Proposes retrieval augmentation for skill selection.

**Relevance to Deverino:** Deverino's skill discovery (`skill list`) could benefit from semantic retrieval rather than just directory scanning. The Vespa integration already points in this direction.

---

### 4. "Skill-as-Pseudocode: Refactoring Skill Libraries to Pseudocode for LLM Agents"
> **Xinze Li, Yuhang Zang, Yixin Cao et al. (4 authors)** — arXiv:2605.27955 (2026-05-27)

Markdown skill libraries ship as **free-form prose**, forcing the agent to re-derive input schema and invocation syntax on every retrieval. This causes errors. Proposes refactoring to pseudocode for clearer schemas.

**Relevance to Deverino:** SKILL.md files should include structured invocation formats (schemas, signatures) alongside prose descriptions. Consider adding a `schema:` block to the skill format.

---

## Tool Selection & Safety

### 5. "When Lower Privileges Suffice: Investigating Over-Privileged Tool Selection in LLM Agents"
> **Kaiyue Yang, Yuyan Bu, Jingwei Yi et al. (8 authors)** — arXiv:2606.20023 (2026-06-18)

LLM agents select tools autonomously. Tool choices among tools with **different privilege levels** become safety-relevant. Prior studies focus on safety-agnostic metadata; this paper investigates whether agents select over-privileged tools when lower-privilege alternatives exist.

**Relevance to Deverino:** Deverino should implement least-privilege tool selection. Skills should declare their privilege level, and the harness should enforce that agents don't escalate unnecessarily.

---

### 6. "AgentGuard: Repurposing Agentic Orchestrator for Safety Evaluation of Tool Orchestration"
> **Jizhou Chen, Samuel Lee Cong** — arXiv:2502.09809 (2025-02-13)

Tool use in LLMs enables agentic systems with real-world impact. Unlike standalone LLMs, **compromised agents can execute malicious workflows** through tool orchestration. Proposes AgentGuard for safety evaluation.

**Relevance to Deverino:** Deverino's workflow runtime needs guardrails. AgentGuard's approach to evaluating tool orchestration safety is directly applicable.

---

### 7. "Small LLMs Are Weak Tool Learners: A Multi-LLM Agent"
> **Weizhou Shen, Chenliang Li, Hongzhan Chen et al. (8 authors)** — arXiv:2401.07324 (2024-01-14)

LLM agents extend standalone LLMs by interacting with external tools (APIs, functions). This paper shows that **small LLMs are weak tool learners** and proposes a multi-LLM agent approach where a stronger model teaches weaker ones.

**Relevance to Deverino:** If Deverino ever supports multiple LLM backends of varying capability, tool-use delegation between models matters.

---

## Key Takeaways for Deverino

1. **SKILL.md format matters** — structured schemas + prose, not just prose
2. **Cross-framework portability** is an unsolved problem Deverino could address
3. **Semantic skill retrieval** (beyond directory scanning) improves selection accuracy
4. **Least-privilege tool selection** is a critical safety property
5. **Tool orchestration safety** needs proactive guardrails, not just post-hoc review
