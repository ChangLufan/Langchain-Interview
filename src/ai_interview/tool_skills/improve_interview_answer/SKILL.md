---
name: improve_interview_answer
description: 针对面试问题和候选人回答，给出更好的回答版本、缺口和改进建议。
func: ai_interview.tool_functions:improve_interview_answer
parameters:
  type: object
  properties:
    question:
      type: string
      description: 面试问题。
    answer:
      type: string
      description: 候选人的原始回答。
  required:
    - question
    - answer
---

Use this tool when the user wants to improve or polish an interview answer.

