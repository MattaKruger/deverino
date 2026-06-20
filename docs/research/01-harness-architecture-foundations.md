# Report 1: Agent Harness Architecture & Foundations

**Generated:** 2026-06-20 | **Sources:** arXiv

---

## Core Concept: What Is an Agent Harness?

### 1. "What makes a harness a harness: necessary and sufficient conditions for an agent harness"
> **Sanderson Oliveira de Macedo** — arXiv:2606.10106 (2026-06-08)

The term "agent harness" names the **layer that wraps a language model and turns it into a coding agent able to act on tools and execution environments**. This paper formalizes the necessary and sufficient conditions for something to qualify as a harness. This is foundational reading for any harness design — it establishes the ontology of what we're building.

**Relevance to Deverino:** Provides a formal definition of the boundary between "just an LLM" and "an agent with a harness." Use this to validate Deverino's architecture against the necessary conditions.

---

### 2. "Agentic Large Language Models, a survey"
> **Aske Plaat, Max van Duijn, Niki van Stein et al. (6 authors)** — arXiv:2503.23037 (2025-03-29)

A comprehensive survey of agentic LLMs — LLMs that act as agents. Reviews the growing body of work and provides a **research agenda**. Covers architectures, planning, tool use, memory, and multi-agent systems.

**Relevance to Deverino:** Use as a literature map. The research agenda section highlights open problems that Deverino could address.

---

### 3. "AI Agents: Evolution, Architecture, and Real-World Applications"
> **Naveen Krishnan** — arXiv:2503.12687 (2025-03-16)

Traces AI agents from early rule-based incarnations to modern systems integrating LLMs. Covers architecture patterns and practical applications.

**Relevance to Deverino:** Historical context. Understands which patterns survived and which didn't.

---

### 4. "Code as Agent Harness"
> **Xuying Ning, Katherine Tieu, Dongqi Fu et al. (42 authors)** — arXiv:2605.18747 (2026-05-18)

Argues that **code itself is the harness** — LLMs demonstrate strong code capabilities from competitive programming to repository-level software engineering. In emerging agent systems, code mediates tool interaction and execution.

**Relevance to Deverino:** Supports the approach of using Python skills/code as the primary harness mechanism. The 42-author team suggests broad consensus on this framing.

---

### 5. "The Semi-Executable Stack: Agentic Software Engineering and the Expanding Scope of SE"
> **Robert Feldt, Per Lenberg, Julian Frattini et al. (4 authors)** — arXiv:2604.15468 (2026-04-16)

AI-based systems driven by **LLMs and tool-using agentic harnesses** are increasingly discussed as a threat to software engineering. Foundation models grow stronger, agents can perform increasingly complex SE tasks.

**Relevance to Deverino:** Frames the competitive landscape — what happens when agentic harnesses scale. Helps Deverino position itself in the expanding scope of SE automation.

---

### 6. "LLM-as-Code Agentic Programming for Agent Harness"
> **Junjia Qi, Zichuan Fu, Jingtong Gao et al. (7 authors)** — arXiv:2606.15874 (2026-06-14)

Argues that every major LLM agent framework gives the LLM the role of orchestrator, causing **token explosion, control-flow hallucination, and limited reasoning depth**. Proposes an alternative where the harness drives control flow and the LLM provides capability.

**Relevance to Deverino:** Challenges the "LLM-as-orchestrator" model. Suggests Deverino's workflow runtime should own control flow, not the LLM.

---

## Key Takeaways for Deverino

1. **A harness is the layer between LLM and tools** — Deverino should be explicit about this boundary
2. **Code-as-harness** is the emerging consensus — Python skills are the right mechanism
3. **LLM-as-orchestrator has fundamental limits** — the harness should own control flow
4. **The field is moving fast** — papers from April–June 2026 show rapid evolution
