---
name: analyze_resume
description: 分析候选人简历，支持传入简历文件路径或简历文本，返回摘要、亮点和风险点。
func: ai_interview.interview_service:analyze_resume
parameters:
  type: object
  properties:
    resume_text:
      type: string
      description: 候选人简历文件路径，或直接粘贴的简历文本。
  required:
    - resume_text
---

Use this tool when the user wants to analyze a resume or prepare interview context from a resume.

