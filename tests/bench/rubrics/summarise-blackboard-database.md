# Rubric: summarise-blackboard-database

## Goal

Summarise what BlackboardDatabase does and how it is structured.

## Hard Assertions

- must_contain: "session"
- must_contain: "SQLite"
- must_contain: "state_proposals"
- must_not_contain: "I don't know"
- min_words: 50
- skill_sequence: [read_memory]

## LLM Judge

threshold: 0.7
model: claude-haiku-4-5-20251001
prompt: |
  Score the following answer 0.0–1.0 on whether it accurately
  describes the BlackboardDatabase's purpose, its key tables,
  and its relationship to session state management.

  Answer: {answer}
