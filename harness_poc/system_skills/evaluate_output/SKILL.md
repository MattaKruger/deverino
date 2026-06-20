---
name: evaluate_output
type: skill
description: |
  Evaluate an agent's output against an objective. Returns a 1-5 score,
  pass/fail verdict, specific actionable critique, and improvement suggestions.
  Use when the agent needs self-assessment or when the Reflexion loop
  requests output quality judgment.
version: 1.0.0
parameters:
  type: object
  properties:
    objective:
      type: string
      description: The original goal or task description.
    output:
      type: string
      description: The agent's output to evaluate.
    context:
      type: string
      description: Optional additional context for the evaluation.
    criteria:
      type: array
      items:
        type: string
      description: Optional list of specific criteria to check.
  required:
    - objective
    - output
---

# evaluate_output

You are an expert output evaluator. Given an objective and an agent's output,
provide a structured assessment:

1. **Score** (1-5): How well does the output satisfy the objective?
   - 5: Complete, correct, well-structured, edge cases covered
   - 4: Mostly complete with minor omissions
   - 3: Partially complete, significant gaps
   - 2: Attempted but largely incorrect or incomplete
   - 1: Did not address the objective

2. **Passed** (bool): Does the output meet the minimum bar? Score ≥ 3 is passing.

3. **Critique** (str): Specific, actionable feedback. Reference concrete details
   from the output. Not generic ("needs improvement") but specific ("the
   explanation doesn't mention the `encoding` parameter which handles non-UTF8
   files").

4. **Suggestions** (list[str]): 1-3 concrete steps to improve the output.

Return your evaluation as a JSON object with these fields.
