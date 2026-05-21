---
name: paper-claim-verification
type: knowledge
description: >-
  Verify that a design document's paper citations are accurate by
  cross-referencing claims against the indexed paper corpus, not just
  abstract or title assumptions.
version: "1.0"
---

# Paper Claim Verification

## Problem

When drafting a technical design document that cites LLM papers, it's easy to:
1. Assume a paper's contribution maps to your design based on its title or abstract alone.
2. Inherit a colleague's citation without checking whether the paper actually supports the claim.
3. Project your own design intent onto a paper instead of reading what it actually says.

This skill provides a systematic process for verifying paper citations against the *actual text* of each paper.

## Prerequisites

- Papers indexed in the Vespa document corpus (`search_documents`)
- The design document you want to verify

## Process

### Step 1: Extract every paper citation from your design doc

Read the design document and make a list of all papers cited. For each citation, note:
- The specific claim being attributed (e.g., "SDOF's FSM -> our mode FSM")
- The paper and section cited (e.g., "SDOF (2605.15204) Section 3.2")
- Whether the citation is for a concept, a mechanism, a result, or a design principle

### Step 2: Search the paper for each claim

For each paper, use `search_documents` with:
- **Query:** The specific concept/term you're attributing (e.g., "intent-stage binding", "Sprint Contract", "distiller")
- **Expand results:** [1, 2, 3] to get the actual text excerpts

### Step 3: Categorize the match

Compare the paper's actual text against what your design document claims:

| Category | Definition | Action |
|---|---|---|
| **Clean mapping** | Paper explicitly describes what you're claiming, in the same domain | Keep the citation, it's solid |
| **Domain-shifted** | Paper's mechanism matches but is validated in a different domain (e.g., enterprise recruitment vs. mode switching) | Keep the citation but add a caveat explaining the domain difference |
| **Pattern only** | Paper's structure is analogous but mechanisms and domain differ | Reclassify as "architectural pattern inspiration" with explicit disclaimers about what doesn't transfer |
| **Wrong attribution** | Paper doesn't actually contain the claimed mechanism, or the mechanism is the opposite of what you claimed | Remove or retract the citation |

### Step 4: For domain-shifted or pattern-only cases, write a caveat

A good caveat has three parts:
1. **What the paper actually says** (quote from the text)
2. **How your design differs** (domain, scale, mechanism)
3. **Why the transfer is still valid** (or what alternative supports your design)

### Step 5: Check for contradictions between papers

Cross-reference the papers against each other:
- Do two papers make incompatible claims about the same mechanism?
- Does one paper's finding undermine another's assumption?
- Does your design combine mechanisms that the papers present as alternatives?

### Step 6: Flag heuristic values that appear paper-validated but aren't

If your design uses numeric thresholds (e.g., "confidence >= 0.5", "max 1024 tokens") and cites a paper, verify:
- Does the paper actually propose this exact threshold?
- Is the threshold validated in a similar operational context?
- Or is it an unrelated constant from a different domain?

If none of the papers provide the threshold, mark it as **heuristic initial value** and add a tuning recommendation.

## Output Format

For each paper cited in your design document, produce a table row:

| Claimed mapping | Paper's actual content | Verdict | Condition |
|---|---|---|---|
| *what you wrote* | *what the paper says* | Clean / DomainShift / Pattern / Wrong | *caveat if needed* |

Then add a **"Known Contradictions and Unresolved Tensions"** section to the design doc listing:
- Every misattribution found and how it was corrected
- Every domain shift and why it's acceptable
- Every heuristic threshold that needs empirical calibration
- Every cross-paper tension that remains unresolved

## Example

See `docs/plans/20260521-plan-mode-vespa-embedding-v2.md` in the repository for a worked example of this process applied to 6 papers.
