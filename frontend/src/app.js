const { createApp, computed, nextTick, onMounted, ref } = Vue

createApp({
  setup() {
    const apiBase = ref('http://127.0.0.1:8000')
    const activeView = ref('assistant')
    const position = ref('AI 应用开发工程师（实习）')
    const mode = ref('file')
    const resumeText = ref('')
    const resumeFile = ref(null)
    const loading = ref(false)
    const evaluating = ref(false)
    const error = ref('')
    const interview = ref(null)
    const answers = ref([])
    const evaluations = ref([])

    const kbFile = ref(null)
    const kbName = ref('')
    const uploading = ref(false)
    const sending = ref(false)
    const assistantError = ref('')
    const knowledgeBases = ref([])
    const assistantMode = ref('knowledge')
    const selectedKnowledgeBaseId = ref('')
    const question = ref('')
    const conversationId = ref('')
    const messages = ref([])
    const conversations = ref([])
    const chatScroll = ref(null)

    const hasInterview = computed(() => Boolean(interview.value))
    const averageScore = computed(() => {
      if (!evaluations.value.length) return 0
      const total = evaluations.value.reduce((sum, item) => sum + (item?.score || 0), 0)
      return Math.round((total / evaluations.value.length) * 10) / 10
    })
    const selectedKnowledgeBase = computed(() =>
      knowledgeBases.value.find((item) => item.id === selectedKnowledgeBaseId.value),
    )
    const assistantConversations = computed(() =>
      conversations.value.filter((item) => ['assistant', 'rag', 'mcp'].includes(item.type)),
    )
    const chatModeLabel = computed(() => {
      if (assistantMode.value === 'normal') return '普通问答'
      if (selectedKnowledgeBase.value) return '单知识库问答'
      return '知识库问答'
    })
    const chatScopeText = computed(() => {
      if (assistantMode.value === 'normal') return '当前使用普通问答，可按需要调用 MCP 工具'
      if (selectedKnowledgeBase.value) {
        return `${selectedKnowledgeBase.value.name} · ${selectedKnowledgeBase.value.chunk_count} 个片段`
      }
      return '系统会根据知识库数量和名称自动选择检索范围，并可按需要调用 MCP 工具'
    })

    function onFileChange(event) {
      resumeFile.value = event.target.files?.[0] || null
    }

    function onKnowledgeFileChange(event) {
      kbFile.value = event.target.files?.[0] || null
      if (kbFile.value && !kbName.value.trim()) {
        kbName.value = kbFile.value.name.replace(/\.[^.]+$/, '')
      }
    }

    async function readJson(response) {
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload.detail || `请求失败：${response.status}`)
      }
      return payload
    }

    function formatTime(value) {
      if (!value) return ''
      return new Date(value).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    }

    async function loadKnowledgeBases() {
      const payload = await readJson(await fetch(`${apiBase.value}/api/rag/knowledge-bases`))
      knowledgeBases.value = payload.items || []
    }

    async function loadConversations() {
      const payload = await readJson(await fetch(`${apiBase.value}/api/conversations`))
      conversations.value = payload.items || []
    }

    async function loadInitialData() {
      try {
        await Promise.all([loadKnowledgeBases(), loadConversations()])
      } catch (err) {
        assistantError.value = err.message
      }
    }

    async function startInterview() {
      error.value = ''
      loading.value = true
      interview.value = null
      evaluations.value = []
      answers.value = []

      try {
        let payload
        if (mode.value === 'file') {
          if (!resumeFile.value) throw new Error('请选择简历文件。')
          const params = new URLSearchParams({
            position: position.value,
            filename: resumeFile.value.name,
          })
          payload = await readJson(
            await fetch(`${apiBase.value}/api/interview/upload?${params}`, {
              method: 'POST',
              headers: { 'Content-Type': resumeFile.value.type || 'application/octet-stream' },
              body: resumeFile.value,
            }),
          )
        } else {
          if (!resumeText.value.trim()) throw new Error('请粘贴简历文本。')
          payload = await readJson(
            await fetch(`${apiBase.value}/api/interview/from-text`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ position: position.value, resume_text: resumeText.value }),
            }),
          )
        }
        interview.value = payload
        answers.value = payload.questions.map(() => '')
      } catch (err) {
        error.value = err.message
      } finally {
        loading.value = false
      }
    }

    async function evaluateAll() {
      if (!interview.value) return
      error.value = ''
      evaluating.value = true
      evaluations.value = []

      try {
        const results = []
        for (const [index, item] of interview.value.questions.entries()) {
          const result = await readJson(
            await fetch(`${apiBase.value}/api/evaluate`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ question: item, answer: answers.value[index] || '' }),
            }),
          )
          results.push(result)
        }
        evaluations.value = results
      } catch (err) {
        error.value = err.message
      } finally {
        evaluating.value = false
      }
    }

    function resetAll() {
      interview.value = null
      answers.value = []
      evaluations.value = []
      error.value = ''
    }

    async function uploadKnowledgeBase() {
      assistantError.value = ''
      if (!kbFile.value) {
        assistantError.value = '请选择要上传的知识库文件。'
        return
      }
      uploading.value = true
      try {
        const params = new URLSearchParams({
          filename: kbFile.value.name,
          name: kbName.value || kbFile.value.name,
        })
        const item = await readJson(
          await fetch(`${apiBase.value}/api/rag/knowledge-bases?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': kbFile.value.type || 'application/octet-stream' },
            body: kbFile.value,
          }),
        )
        await loadKnowledgeBases()
        assistantMode.value = 'knowledge'
        selectedKnowledgeBaseId.value = item.id
        kbFile.value = null
      } catch (err) {
        assistantError.value = err.message
      } finally {
        uploading.value = false
      }
    }

    function scrollChat() {
      nextTick(() => {
        if (chatScroll.value) {
          chatScroll.value.scrollTop = chatScroll.value.scrollHeight
        }
      })
    }

    function parseSseBlock(block) {
      const event = { event: 'message', data: '' }
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event.event = line.slice(6).trim()
        if (line.startsWith('data:')) event.data += line.slice(5).trim()
      }
      return event
    }

    async function readAssistantStream(response, assistantMessage) {
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.detail || `请求失败：${response.status}`)
      }
      const reader = response.body?.getReader()
      if (!reader) throw new Error('当前浏览器不支持流式读取。')

      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let finalPayload = null

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''

        for (const rawBlock of blocks) {
          const block = rawBlock.trim()
          if (!block) continue
          const item = parseSseBlock(block)
          const data = item.data ? JSON.parse(item.data) : {}

          if (item.event === 'delta') {
            assistantMessage.content += data.text || ''
            scrollChat()
          } else if (item.event === 'sources') {
            assistantMessage.sources = data.sources || []
          } else if (item.event === 'tool') {
            assistantMessage.sources = assistantMessage.sources || []
            assistantMessage.sources.push({
              id: `tool-${assistantMessage.sources.length + 1}-${data.name}`,
              type: 'tool',
              name: data.name,
            })
          } else if (item.event === 'done') {
            if (Array.isArray(data.sources) && data.sources.length) {
              assistantMessage.sources = data.sources
            } else if (Array.isArray(data.tools_used) && data.tools_used.length) {
              const seen = new Set((assistantMessage.sources || []).filter((item) => item.type === 'tool').map((item) => item.name))
              assistantMessage.sources = assistantMessage.sources || []
              for (const name of data.tools_used) {
                if (!seen.has(name)) {
                  assistantMessage.sources.push({
                    id: `tool-${assistantMessage.sources.length + 1}-${name}`,
                    type: 'tool',
                    name,
                  })
                  seen.add(name)
                }
              }
            }
            finalPayload = data
          } else if (item.event === 'error') {
            throw new Error(data.detail || '流式输出失败。')
          }
        }
      }

      if (finalPayload) {
        conversationId.value = finalPayload.conversation_id
        messages.value = finalPayload.history || messages.value
        await loadConversations()
      }
    }

    async function sendQuestion() {
      const content = question.value.trim()
      if (!content) return
      assistantError.value = ''
      sending.value = true
      question.value = ''
      messages.value.push({ role: 'user', content })
      const assistantMessage = { role: 'assistant', content: '', sources: [] }
      messages.value.push(assistantMessage)
      scrollChat()

      try {
        await readAssistantStream(
          await fetch(`${apiBase.value}/api/assistant/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              knowledge_base_id:
                assistantMode.value === 'normal' ? '__tools__' : selectedKnowledgeBaseId.value || '__all__',
              conversation_id: conversationId.value,
              message: content,
            }),
          }),
          assistantMessage,
        )
      } catch (err) {
        assistantError.value = err.message
        assistantMessage.content = assistantMessage.content || `发生错误：${err.message}`
      } finally {
        sending.value = false
        scrollChat()
      }
    }

    async function openConversation(item) {
      assistantError.value = ''
      try {
        const payload = await readJson(await fetch(`${apiBase.value}/api/conversations/${item.id}`))
        activeView.value = payload.type === 'interview' ? 'interview' : 'assistant'
        conversationId.value = payload.id
        assistantMode.value = payload.knowledge_base_id ? 'knowledge' : 'normal'
        selectedKnowledgeBaseId.value = payload.knowledge_base_id === '__all__' ? '' : payload.knowledge_base_id || ''
        messages.value = payload.messages || []
        scrollChat()
      } catch (err) {
        assistantError.value = err.message
      }
    }

    async function deleteConversation(item) {
      assistantError.value = ''
      try {
        await readJson(
          await fetch(`${apiBase.value}/api/conversations/${item.id}`, {
            method: 'DELETE',
          }),
        )
        if (conversationId.value === item.id) {
          newConversation()
        }
        await loadConversations()
      } catch (err) {
        assistantError.value = err.message
      }
    }

    function newConversation() {
      conversationId.value = ''
      messages.value = []
      question.value = ''
    }

    onMounted(loadInitialData)

    return {
      apiBase,
      activeView,
      position,
      mode,
      resumeText,
      resumeFile,
      loading,
      evaluating,
      error,
      interview,
      answers,
      evaluations,
      hasInterview,
      averageScore,
      kbFile,
      kbName,
      uploading,
      sending,
      assistantError,
      knowledgeBases,
      assistantMode,
      selectedKnowledgeBaseId,
      selectedKnowledgeBase,
      question,
      conversationId,
      messages,
      conversations,
      assistantConversations,
      chatModeLabel,
      chatScopeText,
      chatScroll,
      onFileChange,
      onKnowledgeFileChange,
      startInterview,
      evaluateAll,
      resetAll,
      uploadKnowledgeBase,
      sendQuestion,
      openConversation,
      deleteConversation,
      newConversation,
      formatTime,
      loadInitialData,
    }
  },
  template: `
    <main class="shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="mark">AI</div>
          <div>
            <h1>AI 面试与知识库助手</h1>
            <p>智能问答、RAG 知识库、面试评估</p>
          </div>
        </div>

        <label class="field">
          <span>API 地址</span>
          <input v-model="apiBase" type="url" @change="loadInitialData" />
        </label>

        <nav class="nav-tabs">
          <button :class="{ active: activeView === 'assistant' }" @click="activeView = 'assistant'">智能问答</button>
          <button :class="{ active: activeView === 'interview' }" @click="activeView = 'interview'">面试助手</button>
        </nav>

        <section v-if="activeView === 'assistant'" class="sidebar-section">
          <div class="section-head">
            <span>知识库</span>
            <button class="text-button" @click="loadInitialData">刷新</button>
          </div>

          <div class="segmented">
            <button :class="{ active: assistantMode === 'normal' }" @click="assistantMode = 'normal'; selectedKnowledgeBaseId = ''">普通问答</button>
            <button :class="{ active: assistantMode === 'knowledge' }" @click="assistantMode = 'knowledge'">知识库问答</button>
          </div>

          <label v-if="assistantMode === 'knowledge'" class="field">
            <span>指定知识库</span>
            <select v-model="selectedKnowledgeBaseId">
              <option value="">不指定，系统自动选择检索范围</option>
              <option v-for="item in knowledgeBases" :key="item.id" :value="item.id">
                {{ item.name }}
              </option>
            </select>
          </label>

          <label class="field">
            <span>知识库名称</span>
            <input v-model="kbName" type="text" placeholder="例如：产品手册" />
          </label>

          <label class="upload compact">
            <input type="file" accept=".pdf,.doc,.docx,.txt,.md,.csv,.json,.html,.htm" @change="onKnowledgeFileChange" />
            <span>{{ kbFile?.name || '上传 RAG 知识库文件' }}</span>
          </label>

          <button class="primary full" :disabled="uploading" @click="uploadKnowledgeBase">
            {{ uploading ? '上传中...' : '上传到 OSS 并入库' }}
          </button>

          <div class="history-list">
            <div class="section-head">
              <span>历史会话</span>
              <button class="text-button" @click="newConversation">新建</button>
            </div>
            <div
              v-for="item in assistantConversations"
              :key="item.id"
              class="history-row"
              :class="{ active: item.id === conversationId }"
            >
              <button class="history-item" @click="openConversation(item)">
                <strong>{{ item.title }}</strong>
                <span>{{ formatTime(item.updated_at) }} · {{ item.message_count }} 条</span>
              </button>
              <button class="delete-history" @click.stop="deleteConversation(item)">删除</button>
            </div>
            <p v-if="!assistantConversations.length" class="muted">暂无历史会话</p>
          </div>
        </section>

        <section v-else class="sidebar-section">
          <label class="field">
            <span>目标岗位</span>
            <input v-model="position" type="text" />
          </label>

          <div class="segmented">
            <button :class="{ active: mode === 'file' }" @click="mode = 'file'">上传简历</button>
            <button :class="{ active: mode === 'text' }" @click="mode = 'text'">粘贴文本</button>
          </div>

          <label v-if="mode === 'file'" class="upload">
            <input type="file" accept=".pdf,.doc,.docx,.txt,.md,.rtf,.html,.htm" @change="onFileChange" />
            <span>{{ resumeFile?.name || '选择简历文件' }}</span>
          </label>

          <label v-else class="field">
            <span>简历文本</span>
            <textarea v-model="resumeText" rows="9"></textarea>
          </label>

          <div class="actions">
            <button class="primary" :disabled="loading" @click="startInterview">
              {{ loading ? '生成中...' : '生成面试' }}
            </button>
            <button class="ghost" @click="resetAll">清空</button>
          </div>
        </section>

        <p v-if="error || assistantError" class="error">{{ error || assistantError }}</p>
      </aside>

      <section class="workspace">
        <template v-if="activeView === 'assistant'">
          <header class="workspace-head">
            <div>
              <h2>智能问答</h2>
              <p>{{ chatScopeText }}</p>
            </div>
            <span class="storage-badge">{{ chatModeLabel }}</span>
          </header>

          <section ref="chatScroll" class="chat-window">
            <div v-if="!messages.length" class="empty chat-empty">
              <h2>输入问题开始对话</h2>
              <p>普通问答可直接调用工具；知识库问答会自动选择检索范围，也可以指定单个知识库。</p>
            </div>
            <article
              v-for="(message, index) in messages"
              :key="index"
              class="message"
              :class="message.role"
            >
              <div class="avatar">{{ message.role === 'user' ? '我' : 'AI' }}</div>
              <div class="bubble">
                <p>{{ message.content }}</p>
                <div v-if="message.sources?.length" class="sources">
                  <span v-for="source in message.sources" :key="source.id">
                    <template v-if="source.type === 'tool'">工具：{{ source.name }}</template>
                    <template v-else>{{ source.knowledge_base_name ? source.knowledge_base_name + ' / ' : '' }}{{ source.source_name }} #{{ source.index }}</template>
                  </span>
                </div>
              </div>
            </article>
          </section>

          <footer class="composer">
            <textarea
              v-model="question"
              rows="3"
              placeholder="输入问题，按 Enter 发送..."
              @keydown.enter.exact.prevent="sendQuestion"
            ></textarea>
            <button class="primary send" :disabled="sending" @click="sendQuestion">
              {{ sending ? '处理中...' : '发送' }}
            </button>
          </footer>
        </template>

        <template v-else>
          <div v-if="!hasInterview" class="empty">
            <h2>上传简历后开始</h2>
            <p>系统会解析简历，提取亮点与风险点，并根据岗位生成 3 个技术面试问题。</p>
          </div>

          <template v-else>
            <section class="summary-grid">
              <div class="panel main-summary">
                <div class="panel-title">
                  <span>简历摘要</span>
                  <strong>{{ interview.resume_analysis.source_name }}</strong>
                </div>
                <p>{{ interview.resume_analysis.summary }}</p>
              </div>

              <div class="panel score-panel">
                <span>平均分</span>
                <strong>{{ evaluations.length ? averageScore : '--' }}</strong>
              </div>
            </section>

            <section class="columns">
              <div class="panel">
                <h2>候选人亮点</h2>
                <ul>
                  <li v-for="item in interview.resume_analysis.highlights" :key="item">{{ item }}</li>
                </ul>
              </div>

              <div class="panel">
                <h2>面试风险点</h2>
                <ul>
                  <li v-for="item in interview.resume_analysis.risk_flags" :key="item">{{ item }}</li>
                </ul>
              </div>
            </section>

            <section class="question-list">
              <article v-for="(item, index) in interview.questions" :key="item" class="question-item">
                <div class="question-head">
                  <span>问题 {{ index + 1 }}</span>
                  <strong v-if="evaluations[index]">{{ evaluations[index].score }} 分</strong>
                </div>
                <p>{{ item }}</p>
                <textarea v-model="answers[index]" rows="5" placeholder="输入候选人回答"></textarea>
                <div v-if="evaluations[index]" class="evaluation">
                  <span :class="evaluations[index].is_correct ? 'pass' : 'fail'">
                    {{ evaluations[index].is_correct ? '回答有效' : '需要追问' }}
                  </span>
                  <p>{{ evaluations[index].feedback }}</p>
                  <ul>
                    <li v-for="point in evaluations[index].missing_points" :key="point">{{ point }}</li>
                  </ul>
                </div>
              </article>
            </section>

            <div class="footer-actions">
              <button class="primary" :disabled="evaluating" @click="evaluateAll">
                {{ evaluating ? '评分中...' : '提交评分' }}
              </button>
            </div>
          </template>
        </template>
      </section>
    </main>
  `,
}).mount('#app')
