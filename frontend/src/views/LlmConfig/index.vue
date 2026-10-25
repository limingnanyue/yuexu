<template>
  <div class="yx-page">
    <PageHeader
      title="模型配置"
      description="连接模型服务，获取可用模型与上下文容量，管理全局默认模型。"
    >
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增模型</el-button>
    </PageHeader>

    <div class="yx-hint">
      支持 OpenAI 兼容接口，包括 DeepSeek、Ollama、豆包和通义千问。
      未绑定专属模型的账号使用默认模型；上下文窗口与最大输出分别配置。
    </div>

    <div class="yx-card">
      <div class="yx-toolbar">
        <span class="muted small">共 {{ models.length }} 个模型</span>
        <div class="yx-toolbar-spacer"></div>
        <span class="muted small">容量单位为 Tokens，未提供时可在编辑中手动填写</span>
      </div>

      <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="load-error" />

      <el-table v-loading="loading" :data="models" row-key="id">
        <el-table-column label="模型配置" min-width="180">
          <template #default="{ row }">
            <div class="model-heading">
              <span class="model-name">{{ row.name }}</span>
              <el-tag v-if="row.is_default" size="small" type="success" effect="plain">默认</el-tag>
            </div>
            <div class="muted small">{{ row.provider || 'openai' }} · {{ row.has_api_key ? 'Key 已配置' : '未配置 Key' }}</div>
          </template>
        </el-table-column>

        <el-table-column label="模型与接口" min-width="220">
          <template #default="{ row }">
            <div class="mono">{{ row.model_name || '—' }}</div>
            <span class="muted small url-text" :title="row.base_url">{{ row.base_url || '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="上下文 / 输出" min-width="190">
          <template #default="{ row }">
            <div>上下文 <span class="capacity-value">{{ formatTokens(row.context_window) }}</span></div>
            <div class="muted small">单次输出 {{ formatTokens(row.max_tokens) }}<template v-if="row.max_output_tokens"> / 上限 {{ formatTokens(row.max_output_tokens) }}</template></div>
          </template>
        </el-table-column>

        <el-table-column label="启用" width="76" align="center">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              :aria-label="`启用模型 ${row.name}`"
              :loading="switchingId === row.id"
              @change="toggleEnabled(row)"
            />
          </template>
        </el-table-column>

        <el-table-column label="操作" width="228" fixed="right">
          <template #default="{ row }">
            <div class="ops-cell">
              <el-button
                link
                type="primary"
                :loading="testingId === row.id"
                @click="testItem(row)"
              >
                测试
              </el-button>
              <el-button
                link
                type="primary"
                :disabled="row.is_default"
                :loading="defaultingId === row.id"
                @click="makeDefault(row)"
              >
                设为默认
              </el-button>
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button
                link
                type="danger"
                :loading="deletingId === row.id"
                @click="removeModel(row)"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="yx-empty">还没有模型，点击右上角「新增模型」接入第一个模型</div>
        </template>
      </el-table>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editId ? '编辑模型' : '新增模型'"
      width="760px"
      destroy-on-close
      :close-on-click-modal="false"
      :close-on-press-escape="!saving"
      :show-close="!saving"
      @close="resetDiscovery"
    >
        <el-form
          ref="modelFormRef"
          :model="form"
          :rules="modelRules"
          label-position="top"
          :disabled="saving"
          @submit.prevent
        >
          <div class="form-section-heading">
            <h3>连接服务</h3>
            <p>接口地址支持域名、/v1 或完整的 /chat/completions 地址。</p>
          </div>
          <div class="form-grid">
            <el-form-item label="名称" prop="name">
              <el-input v-model="form.name" maxlength="64" placeholder="用于区分的模型名称" />
            </el-form-item>
            <el-form-item label="提供方" prop="provider">
              <el-select v-model="form.provider" filterable allow-create default-first-option @change="connectionChanged">
                <el-option v-for="provider in providers" :key="provider.value" :label="provider.label" :value="provider.value" />
              </el-select>
            </el-form-item>
          </div>

          <el-form-item label="接口地址" prop="base_url">
            <el-input
              v-model="form.base_url"
              placeholder="https://api.deepseek.com 或 https://api.deepseek.com/v1"
              @input="connectionChanged"
            />
            <div class="form-tip muted small">系统会自动补全 /chat/completions。</div>
          </el-form-item>

          <el-form-item label="API Key">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              autocomplete="new-password"
              :placeholder="editId ? '地址不变时，留空保留原 Key' : 'sk-...'"
              @input="resetDiscovery"
            />
            <div v-if="editingRow && editingRow.has_api_key" class="form-tip muted small">
              当前 Key：{{ editingRow.api_key }}。地址不变时留空保留；更换服务后请重新填写 Key。
            </div>
            <div v-if="editId" class="form-tip muted small">更换服务地址后，原服务的 Key 和自定义请求头不会自动沿用。</div>
          </el-form-item>

          <div class="form-section-heading">
            <h3>选择模型</h3>
            <p>先获取服务商模型列表，也可以直接输入模型 ID。</p>
          </div>
          <el-form-item label="模型 ID" prop="model_name">
            <div class="model-picker">
              <el-select
                v-model="form.model_name"
                :disabled="discovering"
                filterable allow-create default-first-option
                :reserve-keyword="false"
                placeholder="选择或输入模型 ID，例如 deepseek-chat"
                @change="selectModel"
              >
                <el-option v-for="item in discoveredModels" :key="item.id" :label="item.id" :value="item.id">
                  <span>{{ item.id }}</span>
                  <span class="option-capacity muted small">{{ item.context_window ? formatTokens(item.context_window) + ' 上下文' : '容量未提供' }}</span>
                </el-option>
              </el-select>
              <el-button :icon="Refresh" :loading="discovering" :disabled="!form.base_url.trim()" @click="fetchModels">获取模型</el-button>
            </div>
          </el-form-item>
          <el-alert v-if="discoveryError" :title="discoveryError" type="warning" :closable="false" show-icon class="discovery-notice" />
          <div v-else-if="discoveryDone" class="discovery-notice muted small" role="status">
            已获取 {{ discoveredModels.length }} 个模型。{{ discoveryWarning || '选择模型后填入服务商提供的容量；未提供的字段可手动填写。' }}
          </div>

          <div class="form-grid">
            <el-form-item label="上下文窗口（Tokens）">
              <el-input-number v-model="form.context_window" :min="1" :precision="0" :controls="false" placeholder="未知，可手动填写" />
              <div class="form-tip muted small">输入与输出共享的容量，留空表示未知。</div>
            </el-form-item>
            <el-form-item label="模型输出上限（Tokens）">
              <el-input-number v-model="form.max_output_tokens" :min="1" :precision="0" :controls="false" placeholder="服务商未提供时可留空" />
              <div class="form-tip muted small">模型支持的最大输出，与下方单次输出分开设置。</div>
            </el-form-item>
          </div>

          <div class="yx-hint context-help">容量信息用于配置校验；对话历史仍按「上下文管理」中的条数和时间策略保留。</div>

          <div class="form-section-heading">
            <h3>生成参数</h3>
            <p>根据模型容量设置单次输出，输入内容也会占用上下文。</p>
          </div>

          <div class="form-grid">
            <el-form-item label="单次最大输出（Tokens）" prop="max_tokens">
              <el-input-number
                v-model="form.max_tokens"
                :min="1"
                :precision="0"
                :step="1"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="超时（秒）">
              <el-input-number
                v-model="form.timeout"
                :min="1"
                :max="600"
                :step="1"
                :precision="0"
                controls-position="right"
              />
            </el-form-item>
          </div>

          <el-collapse class="advanced-settings">
            <el-collapse-item title="采样参数 · 温度 / Top P" name="sampling">
              <div class="form-grid">
                <el-form-item label="温度（0–2）">
                  <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" controls-position="right" />
                </el-form-item>
                <el-form-item label="Top P（0–1）">
                  <el-input-number v-model="form.top_p" :min="0" :max="1" :step="0.1" controls-position="right" />
                </el-form-item>
              </div>
            </el-collapse-item>
          </el-collapse>

          <div class="form-grid">
            <el-form-item label="启用">
              <div class="switch-line">
                <el-switch v-model="form.enabled" aria-label="启用此模型" />
                <span class="muted small">停用后不会被调度使用</span>
              </div>
            </el-form-item>
            <el-form-item label="设为默认">
              <div class="switch-line">
                <el-switch v-model="form.is_default" aria-label="设为全局默认模型" />
                <span class="muted small">默认模型全局生效</span>
              </div>
            </el-form-item>
          </div>
        </el-form>

      <template #footer>
        <el-button :disabled="saving" @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="discovering" @click="saveModel">保存配置</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="testVisible" title="模型连通性测试" width="520px">
      <div v-if="testResult" class="test-result">
        <el-alert
          :title="testResult.success ? '连接成功' : '连接失败'"
          :type="testResult.success ? 'success' : 'error'"
          :description="
            testResult.success
              ? `耗时 ${testResult.latency_ms} ms`
              : testResult.error || '未知错误'
          "
          :closable="false"
          show-icon
        />
        <div v-if="testResult.content" class="test-block">
          <div class="muted small test-label">模型回复</div>
          <pre class="prompt-pre">{{ testResult.content }}</pre>
        </div>
      </div>
      <div v-else class="yx-empty">正在测试连接…</div>
      <template #footer>
        <el-button @click="testVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import {
  createModel,
  deleteModel,
  discoverModels,
  listModels,
  setDefaultModel,
  testModel,
  updateModel,
} from '@/api/model'

const models = ref([])
const loading = ref(false)
const loadError = ref('')
const dialogVisible = ref(false)
const editId = ref('')
const editingRow = ref(null)
const saving = ref(false)
const modelFormRef = ref(null)
const switchingId = ref('')
const defaultingId = ref('')
const testingId = ref('')
const deletingId = ref('')

const testVisible = ref(false)
const testResult = ref(null)
const discoveredModels = ref([])
const discovering = ref(false)
const discoveryDone = ref(false)
const discoveryError = ref('')
const discoveryWarning = ref('')
let discoveryVersion = 0

const providers = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI / 兼容服务' },
  { value: 'ollama', label: 'Ollama（本地）' },
  { value: 'qwen', label: '通义千问' },
  { value: 'doubao', label: '豆包' },
  { value: 'openrouter', label: 'OpenRouter' },
]

const modelRules = {
  name: [{ required: true, whitespace: true, message: '请输入模型名称', trigger: 'blur' }],
  base_url: [{ required: true, whitespace: true, message: '请输入接口地址', trigger: 'blur' }],
  model_name: [{ required: true, whitespace: true, message: '请输入或选择模型 ID', trigger: 'change' }],
  max_tokens: [{ required: true, type: 'number', min: 1, message: '请填写单次最大输出，至少为 1', trigger: 'blur' }],
}

function defaultForm() {
  return {
    name: '',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com',
    api_key: '',
    model_name: 'deepseek-chat',
    temperature: 0.8,
    top_p: 1,
    max_tokens: 1024,
    context_window: null,
    max_output_tokens: null,
    timeout: 60,
    enabled: true,
    is_default: false,
  }
}

const form = reactive(defaultForm())

function formatTokens(value) {
  return value > 0 ? Number(value).toLocaleString('zh-CN') : '未配置'
}

function resetDiscovery() {
  discoveryVersion++
  discovering.value = false
  discoveredModels.value = []
  discoveryDone.value = false
  discoveryError.value = ''
  discoveryWarning.value = ''
}

function connectionChanged() {
  resetDiscovery()
  form.context_window = null
  form.max_output_tokens = null
}

function selectModel(id) {
  const selected = discoveredModels.value.find(item => item.id === id)
  form.context_window = selected?.context_window ?? null
  form.max_output_tokens = selected?.max_output_tokens ?? null
  if (form.provider === 'ollama' && selected && !selected.context_window) return fetchModels()
}

async function fetchModels() {
  if (discovering.value || !form.base_url.trim()) return
  const version = ++discoveryVersion
  discovering.value = true
  discoveryError.value = ''
  try {
    const payload = {
      base_url: form.base_url.trim(),
      provider: form.provider.trim(),
      model_name: form.model_name.trim(),
    }
    if (editId.value) payload.model_id = editId.value
    if (form.api_key.trim()) payload.api_key = form.api_key.trim()
    const data = await discoverModels(payload)
    if (version !== discoveryVersion) return
    discoveredModels.value = data.models || []
    discoveryDone.value = true
    discoveryWarning.value = data.warning || ''
    const selected = discoveredModels.value.find(item => item.id === form.model_name)
    if (selected) {
      form.context_window = selected.context_window ?? form.context_window
      form.max_output_tokens = selected.max_output_tokens ?? form.max_output_tokens
    }
  } catch (error) {
    if (version !== discoveryVersion) return
    discoveryError.value = error.response?.data?.message || error.message || '获取失败，请检查接口地址与 Key 后重试；仍可手动配置。'
  } finally {
    if (version === discoveryVersion) discovering.value = false
  }
}

async function load() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const data = await listModels()
    models.value = Array.isArray(data) ? data : []
  } catch {
    loadError.value = '模型列表加载失败，请点击右上角刷新重试。'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  resetDiscovery()
  editId.value = ''
  editingRow.value = null
  Object.assign(form, defaultForm())
  dialogVisible.value = true
  nextTick(() => modelFormRef.value?.clearValidate())
}

function openEdit(row) {
  resetDiscovery()
  editId.value = row.id
  editingRow.value = row
  Object.assign(form, {
    name: row.name || '',
    provider: row.provider || 'openai',
    base_url: row.base_url || '',
    api_key: '',
    model_name: row.model_name || '',
    temperature: row.temperature ?? 0.8,
    top_p: row.top_p ?? 1,
    max_tokens: row.max_tokens ?? 1024,
    context_window: row.context_window ?? null,
    max_output_tokens: row.max_output_tokens ?? null,
    timeout: row.timeout ?? 60,
    enabled: row.enabled !== false,
    is_default: !!row.is_default,
  })
  dialogVisible.value = true
  nextTick(() => modelFormRef.value?.clearValidate())
}

async function saveModel() {
  if (saving.value || discovering.value) return
  try {
    await modelFormRef.value.validate()
  } catch {
    return
  }
  if (saving.value) return
  const limit = Math.min(form.context_window || Infinity, form.max_output_tokens || Infinity)
  if (form.max_tokens > limit) {
    ElMessage.warning(`单次最大输出不能超过模型容量 ${formatTokens(limit)} Tokens，请调整输出或容量配置`)
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      provider: form.provider.trim() || 'openai',
      base_url: form.base_url.trim(),
      model_name: form.model_name.trim(),
      temperature: form.temperature,
      top_p: form.top_p,
      max_tokens: form.max_tokens,
      context_window: form.context_window ?? null,
      max_output_tokens: form.max_output_tokens ?? null,
      timeout: form.timeout,
      enabled: form.enabled,
      is_default: form.is_default,
    }
    const apiKey = form.api_key.trim()
    if (apiKey) payload.api_key = apiKey

    if (editId.value) {
      await updateModel(editId.value, payload)
      ElMessage.success('模型配置已更新')
    } else {
      await createModel(payload)
      ElMessage.success('模型已创建')
    }
    dialogVisible.value = false
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row) {
  const enabled = row.enabled
  switchingId.value = row.id
  try {
    await updateModel(row.id, { enabled })
    ElMessage.success(enabled ? '模型已启用' : '模型已停用')
  } catch {
    row.enabled = !enabled
  } finally {
    switchingId.value = ''
  }
}

async function makeDefault(row) {
  defaultingId.value = row.id
  try {
    await setDefaultModel(row.id)
    ElMessage.success(`已将「${row.name}」设为默认模型`)
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    defaultingId.value = ''
  }
}

async function testItem(row) {
  testingId.value = row.id
  testResult.value = null
  try {
    const data = await testModel(row.id)
    testResult.value = data
    testVisible.value = true
    if (data?.success) {
      ElMessage.success(`连接成功，耗时 ${data.latency_ms} ms`)
    } else {
      ElMessage.warning(data?.error || '模型连接失败')
    }
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    testingId.value = ''
  }
}

async function removeModel(row) {
  if (row.is_default) {
    ElMessage.warning('默认模型不能直接删除，请先切换默认模型')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定删除模型「${row.name}」吗？此操作不可恢复。`,
      '删除模型',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  deletingId.value = row.id
  try {
    await deleteModel(row.id)
    ElMessage.success('模型已删除')
    await load()
  } catch {
    // 默认模型会被后端拒绝，错误提示由请求拦截器统一展示
  } finally {
    deletingId.value = ''
  }
}

onMounted(load)
</script>

<style scoped>
.model-heading {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 4px;
}

.capacity-value {
  font-variant-numeric: tabular-nums;
  color: var(--yx-text);
}

.model-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--yx-text);
}

.url-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-cell {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 10px;
}

.ops-cell :deep(.el-button + .el-button) {
  margin-left: 0;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}

.form-grid :deep(.el-input-number),
.model-picker :deep(.el-select) {
  width: 100%;
}

.form-section-heading {
  margin: 28px 0 20px;
  padding-top: 24px;
  border-top: 1px solid var(--yx-line);
}

.form-section-heading:first-child {
  margin-top: 4px;
  padding-top: 0;
  border-top: 0;
}

.form-section-heading h3 {
  margin: 0 0 6px;
  color: var(--yx-text);
  font-size: 14px;
  font-weight: 600;
}

.form-section-heading p {
  margin: 0;
  color: var(--yx-muted);
  font-size: 13px;
  line-height: 1.7;
}

.model-picker {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.model-picker :deep(.el-select) {
  min-width: 0;
  flex: 1;
}

.option-capacity {
  margin-left: 16px;
}

.discovery-notice {
  margin: -4px 0 18px;
  line-height: 1.8;
}

.load-error {
  margin-bottom: 16px;
}

.context-help {
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.advanced-settings {
  margin: 0 0 20px;
}

.advanced-settings :deep(.el-collapse-item__content) {
  padding: 12px 0 0;
}

.form-tip {
  width: 100%;
  margin-top: 4px;
  line-height: 1.6;
}

.switch-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 32px;
}

.test-block {
  margin-top: 16px;
}

.test-label {
  margin-bottom: 8px;
}

.prompt-pre {
  margin: 0;
  max-height: 32vh;
  overflow: auto;
  padding: 14px;
  border: 1px solid var(--yx-line);
  border-radius: 12px;
  background: var(--yx-elevated);
  color: var(--yx-text-2);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 700px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .model-picker {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
  }

  .model-picker :deep(.el-select) {
    flex: auto;
  }
}
</style>
