---
name: match_knowledge_base_name
description: 根据用户问题和知识库名称列表，判断问题是否明确指向某个知识库。
func: ai_interview.tool_functions:match_knowledge_base_name
parameters:
  type: object
  properties:
    question:
      type: string
      description: 用户问题。
    knowledge_base_names:
      type: string
      description: 知识库名称列表，或用逗号分隔的名称字符串。
  required:
    - question
    - knowledge_base_names
---

Use this tool when the user wants to route a question to the most relevant knowledge base by name.
