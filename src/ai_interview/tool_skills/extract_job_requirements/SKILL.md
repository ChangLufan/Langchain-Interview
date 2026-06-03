---
name: extract_job_requirements
description: 从岗位描述中提取必备技能、加分技能、职责和面试关注点。
func: ai_interview.tool_functions:extract_job_requirements
parameters:
  type: object
  properties:
    job_description:
      type: string
      description: 岗位 JD、招聘要求或岗位说明文本。
  required:
    - job_description
---

Use this tool when the user provides a job description and wants structured interview criteria.

