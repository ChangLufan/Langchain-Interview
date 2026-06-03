---
name: generate_questions
description: 根据岗位名称和简历摘要生成 3 个技术面试问题。
func: ai_interview.interview_service:generate_questions
parameters:
  type: object
  properties:
    position:
      type: string
      description: 岗位名称。
    resume_summary:
      type: string
      description: 简历摘要。
  required:
    - position
    - resume_summary
---

Use this tool when the user wants interview questions tailored to a role and candidate profile.

