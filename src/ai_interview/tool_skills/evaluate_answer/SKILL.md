---
name: evaluate_answer
description: 评估候选人对某个面试问题的回答，返回是否正确、分数、反馈和缺失点。
func: ai_interview.interview_service:evaluate_answer
parameters:
  type: object
  properties:
    question:
      type: string
      description: 面试问题。
    answer:
      type: string
      description: 候选人的回答。
  required:
    - question
    - answer
---

Use this tool when the user wants to score or review a candidate answer.

