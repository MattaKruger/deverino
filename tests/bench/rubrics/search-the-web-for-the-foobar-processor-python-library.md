# Rubric: search-the-web-for-the-foobar-processor-python-library

## Goal

Search the web for the foobar_processor Python library.

## Hard Assertions

- must_contain: "foobar_processor"
- must_contain: "not found"
- must_contain: "no further"
- must_not_contain: "I couldn't find much"
- must_not_contain: "third search"
- must_not_contain: "different search tool"
- min_words: 20
- skill_sequence: [web_search, web_search]

## LLM Judge

threshold: 0.7
model: claude-haiku-4-5-20251001
prompt: |
  Score the following answer on a scale of 0.0 to 1.0 based on how well it meets these criteria:
  - Clearly states that 'foobar_processor' was searched for.
  - States that the library was not found or is unavailable.
  - Indicates that no further search attempts will be made.
  - Does not contain any speculation, hallucination, or fabricated details about the library.
  - Does not mention using any alternative search tools or a third search.
  - The language is plain and direct, not vague.
  
  A score of 1.0 means the answer perfectly satisfies all criteria. A score of 0.0 means it fails critically.
  
  Answer: {answer}
