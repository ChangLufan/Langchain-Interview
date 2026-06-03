# AI_interview 项目运行测试报告

测试时间：2026-06-01  
工作目录：`F:\PythonProject\easy-langent`  
Python 环境：`F:\PythonProject\pythonProject\.venv\Scripts\python.exe`  
简历文件：`src/interview/interview.pdf`

## 1. 测试结论

- 指定虚拟环境可用，Python 版本为 `3.12.4`。
- 依赖 `python-dotenv`、`langchain-core`、`langchain-openai`、`tika` 均已在指定环境中存在，无需额外安装。
- 环境变量 `AI_BAILIAN_API_KEY` 可读取，DashScope 兼容 OpenAI 接口可调用。
- `src/interview/interview.pdf` 可被 Apache Tika 成功解析，解析文本长度为 `2456` 字符。
- MCP 工具调用链路可运行，能够调用 `analyze_resume`、`generate_questions`、`evaluate_answer` 等工具。
- 交互式面试入口 `python AI_interview.py` 可运行，能完成简历分析、生成问题、读取候选人回答、逐题评分并输出 JSON 报告。

## 2. 本次修复与调整

测试中发现 Qwen 模型默认开启 thinking 模式时，严格 JSON Prompt 可能返回解释文本或空 `content`，导致 `LLM 未返回合法 JSON`。已在以下位置修复：

- `src/ai_interview/llm.py`：`invoke_llm_json()` 调用 LLM 时增加 `extra_body={"enable_thinking": False}`。
- `src/ai_interview/mcp_client.py`：MCP tool calling 调用 LLM 时增加 `extra_body={"enable_thinking": False}`。
- `src/ai_interview/config.py`：`MAX_TOOL_ROUNDS` 从 `5` 调整为 `8`，避免复杂工具会话过早被截断。
- `scripts/run_ai_interview_smoke.py`：新增 smoke 测试脚本，用 UTF-8 捕获 MCP 和交互式面试结果。

## 3. 简历解析结果

解析元信息：

```json
{
  "source_type": "file",
  "source_name": "interview.pdf",
  "content_type": "application/pdf"
}
```

简历摘要：

> 硕士在读，GPA前5%，中共党员。专注AI应用后端开发，熟悉Spring Boot、RAG及Agent技术。主导两个大模型项目，具备简历解析、语音交互及异步架构优化经验，技术栈匹配度高，实习意向明确。

识别出的亮点：

- 学术优异：硕士 GPA 3.91/5（前 5%），获省级优秀毕业生及多项奖学金，基础扎实。
- 架构优化：设计 Redis Stream 异步解耦耗时任务，接口响应从 15s 降至 200ms。
- 全链路实现：完成从文档解析 Tika、向量化 RAG 到语音流式交互 WebSocket + ASR/TTS 的闭环开发。
- 工程落地：使用 Skill 驱动出题、Function Calling 及多轮会话管理，具备实际业务场景解决能力。

识别出的风险点：

- 简历中部分项目时间位于未来，需要核实时间线真实性。
- Java 多线程、锁机制等底层能力需要通过追问验证深度。
- 简历提到 Cursor/Codex 等 AI 编程工具，需要确认是否具备独立调试与核心逻辑掌控能力。
- 两个项目均涉及较新的 LLM 应用框架，需要核实候选人的具体贡献边界。

## 4. MCP 会话测试

### 4.1 简单 MCP 会话

用户输入：

> 请只调用 analyze_resume 工具一次分析 src/interview/interview.pdf，然后直接用 3 条要点总结候选人，不要调用其他工具。

实际工具调用：

- `analyze_resume`
- `generate_questions`
- `evaluate_answer` x 3

说明：模型没有完全遵守“只调用 analyze_resume”的限制，继续生成问题并评估了模拟回答。但 MCP 工具链本身成功跑通，最终返回了完整面试评估文本。

MCP 返回摘要：

> 根据简历分析，该候选人基础扎实（GPA前5%），在AI应用落地方面具备实战经验，特别是在RAG和Agent开发上。但在分布式事务、高并发场景及底层原理深度上可能存在不足。

MCP 生成的问题与模拟评估：

| 序号 | 问题 | 模拟评分 | 反馈摘要 |
| --- | --- | --- | --- |
| 1 | 请结合你简历中的AI项目，详细阐述在RAG架构中如何解决向量检索的精度问题以及长上下文带来的延迟挑战？ | 45 | 回答过于简略，缺少 Rerank、Query Rewriting、检索效率与准确性权衡等细节。 |
| 2 | 在Agent开发过程中，你是如何利用异步解耦技术处理大模型推理的高耗时场景，并确保分布式环境下的数据一致性与事务完整性的？ | 45 | 只提到 Redis Stream 和本地消息表，缺少幂等、补偿、可靠消息投递等方案。 |
| 3 | 当面对大模型幻觉或不可控输出时，你在工程层面设计了哪些具体的容错机制与降级策略来保障后端服务的稳定性与用户体验？ | 45 | 规则校验和静态降级偏浅，缺少 RAG 溯源、结构化输出约束、人工反馈闭环等机制。 |

### 4.2 复杂 MCP 会话暴露的问题

复杂提示要求“分析简历、生成 3 个问题、总结”时，模型会持续追加 `evaluate_answer` 或二次 `generate_questions` 调用，直到超过 `MAX_TOOL_ROUNDS=8`：

```text
RuntimeError: 超过最大工具调用轮数 8，请缩小问题范围后重试。
```

结论：MCP 基础链路可用，但当前 `chat_with_tools()` 对模型工具调用缺少强约束。后续建议增加会话级任务状态，例如“已分析”“已出题”“已评分”，并在系统提示中明确禁止重复调用同类工具。

## 5. 交互式面试测试

执行入口：

```powershell
F:\PythonProject\pythonProject\.venv\Scripts\python.exe AI_interview.py
```

输入内容：

- 模式：`2`，交互式面试
- 岗位：`AI 应用开发工程师（实习）`
- 简历：`src/interview/interview.pdf`

生成的问题：

1. 请结合简历分析项目，详细说明你在RAG链路中如何处理检索噪声以提升最终回答的准确率？
2. 在实现语音流式交互时，你是如何设计异步架构以平衡首字延迟与系统吞吐量的？
3. 当向量数据库返回的Top-K结果存在语义冲突或幻觉风险时，你的后端服务采取了哪些具体的校验或降级策略？

我输入的回答：

1. 我会先用 Apache Tika 解析 PDF、Word 等多格式简历，抽取文本后做控制字符、异常换行、空白符和嵌入元素噪声清洗。进入 LLM 前会限制输入长度，保留教育背景、项目经历、技术栈和求职意向等关键信息。Prompt 上要求模型只输出固定 JSON，包括 summary、highlights 和 risk_flags；服务层再做 JSON 提取、字段校验、异常兜底和错误提示，保证下游出题模块拿到稳定结构。
2. 在 RAG 知识库里，我会先按语义段落或标题层级做文档分块，设置合理 chunk size 和 overlap，避免切断关键上下文。每个块生成向量后存入 pgvector，并用 HNSW 索引提升近邻检索性能。查询阶段会向量化用户问题，召回 TopK 片段，再结合相似度阈值、元数据过滤和必要的重排序减少无关片段。工程上还要控制上下文长度，避免把低相关内容塞进模型导致 Token 浪费和幻觉。
3. Redis Stream 适合把耗时任务从同步请求链路里解耦。接口收到简历分析或向量化请求后，只写入任务消息并返回 taskId；消费者组异步执行 LLM 调用或 embedding 计算，完成后把状态和结果写回数据库或缓存。这样核心接口不用等待十几秒的推理过程，可以快速响应。落地时我会处理消息确认、失败重试、幂等键、死信队列和任务状态一致性，避免重复消费或任务丢失。

评分结果：

| 序号 | 分数 | 是否正确 | 反馈摘要 |
| --- | --- | --- | --- |
| 1 | 45 | false | 回答偏离 RAG 检索噪声处理主题，只描述了简历解析和结构化提取，缺少向量检索、重排序、查询改写、上下文过滤等内容。 |
| 2 | 10 | false | 题目问语音流式交互的异步架构，回答却描述 RAG 检索流程，属于答非所问。 |
| 3 | 20 | false | 题目问向量检索结果冲突和幻觉风险的校验/降级，回答却描述 Redis Stream 异步解耦，属于答非所问。 |

平均分：`25.0`

交互式面试功能结论：功能链路正常，评分结果合理地识别了回答与问题不匹配的问题。

## 6. 运行产物

- `AI_interview_test_report.md`：本测试报告。
- `ai_interview_smoke_result.json`：统一 smoke 测试原始结果。
- `mcp_simple_result.json`：简单 MCP 会话原始结果。
- `interactive_test_result.json`：交互式面试单次测试原始结果。
- `scripts/run_ai_interview_smoke.py`：自动化 smoke 测试脚本。

## 7. 后续建议

- 为 MCP 客户端增加系统提示，明确“何时停止调用工具、何时输出最终答案”。
- 在 `MCPClient.chat_with_tools()` 中增加同类工具调用次数限制，避免模型反复调用 `evaluate_answer`。
- 给 CLI 增加非交互参数模式，例如 `--mode interview --position ... --resume ... --answers answers.json`，方便自动化测试。
- 将 `extra_body={"enable_thinking": False}` 封装为统一 LLM 调用参数，避免后续新增调用点遗漏。
