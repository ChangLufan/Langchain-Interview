---
name: summarize_conversation
description: 总结面试或问答会话，提炼摘要、结论和后续事项。
func: ai_interview.tool_functions:summarize_conversation
parameters:
  type: object
  properties:
    notes:
      type: string
      description: 会话记录、面试记录或长文本笔记。
  required:
    - notes
---

Use this tool when the user wants a concise summary of an interview or assistant conversation.

