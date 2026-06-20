# Report 3: Memory, Persistence & Blackboard Systems

**Generated:** 2026-06-20 | **Sources:** arXiv

---

## Blackboard Architecture for LLM Agents

### 1. "Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture"
> **Bochen Han, Songmao Zhang** — arXiv:2507.01701 (2025-07-02)

Proposes incorporating **blackboard architecture** into LLM multi-agent systems so that: (1) agents with various roles can **share all information and others' messages** during collaboration, and (2) the system has a **centralized, inspectable state**.

**Relevance to Deverino:** **This is the single most relevant paper to Deverino's architecture.** Deverino uses a PostgreSQL blackboard as its runtime state. This paper validates that design choice and provides patterns for structuring multi-agent communication through the blackboard.

**Key patterns:**
- Agents post partial results to the blackboard
- Other agents read and build upon those results
- The blackboard serves as both working memory and communication channel

---

### 2. "Distilling Feedback into Memory-as-a-Tool"
> **Víctor Gallego** — arXiv:2601.05960 (2026-01-09)

Proposes a framework that **amortizes the cost of inference-time reasoning** by converting transient critiques into retrievable guidelines, through a **file-based memory system and agent-controlled tool calls**.

**Relevance to Deverino:** Deverino's state consolidation and changelog serve a similar purpose — converting ephemeral agent reasoning into durable, queryable state. This paper provides formal grounding for that pattern.

---

## Persistent Memory & KV Cache

### 3. "Agent Memory Below the Prompt: Persistent Q4 KV Cache for Multi-Agent LLM Inference on Edge Devices"
> **Yakov Pyotr Shkolnikov** — arXiv:2603.04428 (2026-02-17)

Multi-agent LLM systems on edge devices face memory management: device RAM is too small to hold every agent's KV cache simultaneously. Proposes **persistent quantized KV cache** to share context across agents.

**Relevance to Deverino:** While Deverino runs server-side, the concept of sharing context across agents via persistent cache is relevant to multi-agent workflows. Could inform how the blackboard caches agent context.

---

## Security Risks of Persistent Agent Memory

### 4. "Zombie Agents: Persistent Control of Self-Evolving LLM Agents via Self-Reinforcing Injections"
> **Xianglin Yang, Yufei He, Shuo Ji et al. (5 authors)** — arXiv:2602.15654 (2026-02-17)

Self-evolving LLM agents update their **internal state across sessions**, often by writing and reusing long-term memory. This improves long-horizon task performance but creates a **security risk**: malicious injections can persist across sessions.

**Relevance to Deverino:** Deverino's durable state (PostgreSQL blackboard) is exactly this pattern. The "Zombie Agent" threat model is directly relevant: what if a skill or workflow writes malicious state that persists? Needs state validation/sandboxing.

---

### 5. "Replayable Financial Agents: A Determinism-Faithfulness Assurance Harness for Tool-Using LLM Agents"
> **Raffi Khatchadourian** — arXiv:2601.15322 (2026-01-17)

LLM agents struggle with **regulatory audit replay**: when asked to reproduce a flagged transaction decision with identical inputs, many deployments fail to return consistent results. Introduces the Determinism-Faithfulness Assurance harness.

**Relevance to Deverino:** Deverino's changelog and state history partially address this, but a formal replay mechanism would strengthen auditability. The paper provides patterns for deterministic replay of agent decisions.

---

## Key Takeaways for Deverino

1. **Blackboard architecture is validated** — the Han & Zhang paper directly supports Deverino's design
2. **Memory-as-tool** is the right abstraction — converting reasoning to durable, queryable state
3. **Cross-agent context sharing** via persistent state is an active research area
4. **Security of persistent state** ("Zombie Agents") is a real concern — needs mitigation
5. **Deterministic replay** of agent decisions is a valuable property for debugging and audit
