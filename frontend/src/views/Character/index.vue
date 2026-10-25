<template>
  <div class="yx-page character-page">
    <PageHeader title="人设管理" description="性格、语气、禁忌与 System Prompt">
      <el-button :icon="Upload" @click="openImport">导入人设</el-button>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建人设</el-button>
    </PageHeader>

    <div class="yx-card search-card">
      <div class="yx-toolbar search-toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索人设名称或描述"
          clearable
          :prefix-icon="Search"
          class="search-input"
          aria-label="搜索人设名称或描述"
          @keyup.enter="search"
          @clear="search"
        />
        <el-button :icon="Search" @click="search">搜索</el-button>
        <div class="yx-toolbar-spacer"></div>
        <span class="muted small">共 {{ total }} 个人设</span>
      </div>
    </div>

    <div v-loading="loading" class="char-list">
      <div v-if="characters.length" class="yx-grid yx-grid-2">
        <div v-for="item in characters" :key="item.id" class="yx-card char-card">
          <div class="char-head">
            <h3>{{ item.name }}</h3>
            <div class="char-tags">
              <el-tag size="small" :type="scopeTagType(item.scope)" effect="plain">
                {{ scopeLabel(item.scope) }}
              </el-tag>
              <el-tag v-if="item.is_default" size="small" type="success" effect="plain">
                默认
              </el-tag>
              <el-tag
                size="small"
                :type="item.enabled ? 'success' : 'info'"
                effect="plain"
              >
                {{ item.enabled ? '启用' : '停用' }}
              </el-tag>
            </div>
          </div>

          <p class="char-desc">{{ item.description || '暂无简介' }}</p>

          <div class="char-meta muted small">
            <span>表情键 {{ (item.emoji_keys || []).length }} 个</span>
            <span>更新于 {{ formatDateTime(item.updated_at) }}</span>
          </div>

          <div class="char-actions">
            <el-button link type="primary" :icon="Edit" @click="openEdit(item)">
              编辑
            </el-button>
            <el-button
              link
              type="primary"
              :icon="Star"
              :disabled="item.is_default"
              :loading="defaultingId === item.id"
              @click="makeDefault(item)"
            >
              设为默认
            </el-button>
            <el-button
              link
              :icon="View"
              :loading="previewingId === item.id"
              @click="openPreview(item)"
            >
              查看完整人设
            </el-button>
            <el-button
              link
              :icon="Download"
              :loading="exportingId === item.id"
              @click="exportItem(item)"
            >
              导出
            </el-button>
            <el-button
              link
              type="danger"
              :icon="Delete"
              :loading="deletingId === item.id"
              @click="removeItem(item)"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>

      <div v-else-if="!loading" class="yx-card">
        <el-empty :description="emptyText" :image-size="72">
          <el-button type="primary" :icon="Plus" @click="openCreate">新建人设</el-button>
        </el-empty>
      </div>
    </div>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      @current-change="handlePageChange"
    />

    <el-dialog
      v-model="dialogVisible"
      :title="editId ? '编辑人设' : '新建人设'"
      width="760px"
      top="5vh"
      :close-on-click-modal="false"
    >
      <el-scrollbar max-height="66vh">
        <el-form
          ref="characterFormRef"
          :model="form"
          :rules="characterRules"
          label-position="top"
          @submit.prevent
        >
          <div class="form-grid">
            <el-form-item label="名称" prop="name">
              <el-input v-model="form.name" maxlength="64" placeholder="例如：小满" />
            </el-form-item>
            <el-form-item label="生效范围" prop="scope">
              <el-select v-model="form.scope">
                <el-option
                  v-for="option in scopeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </el-form-item>
          </div>

          <el-form-item label="基础信息 / 人设简介">
            <el-input
              v-model="form.description"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 8 }"
              maxlength="500"
              show-word-limit
              placeholder="一句话概括这个角色，例如：活泼亲近、记性超好的同龄好朋友"
            />
          </el-form-item>

          <div class="form-grid">
            <el-form-item label="性格特质">
              <el-input
                v-model="form.personality"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="元气、清爽、亲近、松弛，会接梗、会倾听"
              />
            </el-form-item>
            <el-form-item label="对话风格规范">
              <el-input
                v-model="form.speaking_style"
                type="textarea"
                :autosize="{ minRows: 6, maxRows: 12 }"
                placeholder="简短自然的中文口语，不堆砌辞藻"
              />
            </el-form-item>
          </div>

          <div class="form-grid">
            <el-form-item label="背景故事">
              <el-input
                v-model="form.background"
                type="textarea"
                :autosize="{ minRows: 6, maxRows: 12 }"
                placeholder="这个角色是谁、过着怎样的生活——TA 的经历、职业、日常轨迹，越具体越有生活感"
              />
            </el-form-item>
            <el-form-item label="人格禁止项 / 禁止话题">
              <el-input
                v-model="form.taboos"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="政治敏感、违法违规内容"
              />
            </el-form-item>
          </div>

          <el-divider content-position="left">背景扩展</el-divider>
          <p class="muted small">让角色拥有可聊的生活细节：兴趣爱好与社交关系会成为自然话题来源；生活作息按当前时间推导「现在在干嘛」，与情感系统的动态背景联动。</p>
          <div class="form-grid">
            <el-form-item label="兴趣爱好">
              <el-input
                v-model="form.hobbies"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="追剧、打游戏、探店、听歌……聊到相关话题时会更真实"
              />
            </el-form-item>
            <el-form-item label="社交关系">
              <el-input
                v-model="form.social_circle"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="好朋友、家人、同事……提到社交生活时更有真实感"
              />
            </el-form-item>
          </div>

          <el-form-item label="生活作息（决定 TA 现在大概在干嘛）">
            <div class="schedule-editor">
              <div v-for="(slot, index) in form.life_schedule" :key="index" class="schedule-row">
                <el-input
                  v-model="slot.start"
                  maxlength="5"
                  placeholder="00:00"
                  :aria-label="`时段 ${index + 1} 开始时间`"
                  class="schedule-time"
                />
                <span class="schedule-sep">至</span>
                <el-input
                  v-model="slot.end"
                  maxlength="5"
                  placeholder="24:00"
                  :aria-label="`时段 ${index + 1} 结束时间`"
                  class="schedule-time"
                />
                <el-input
                  v-model="slot.activity"
                  maxlength="60"
                  placeholder="在干嘛，例如：晚上的自由时间，追剧打游戏"
                  class="schedule-activity"
                />
                <el-button
                  link
                  type="danger"
                  :icon="Delete"
                  :disabled="form.life_schedule.length <= 1"
                  :aria-label="`删除时段 ${index + 1}`"
                  @click="form.life_schedule.splice(index, 1)"
                />
              </div>
              <p class="muted small schedule-hint">时间使用 HH:mm 格式，24:00 表示当天结束。</p>
              <el-button link type="primary" :icon="Plus" @click="addScheduleSlot">
                添加时段
              </el-button>
            </div>
          </el-form-item>

          <el-form-item label="回复底线">
            <el-input
              v-model="form.red_lines"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 6 }"
              placeholder="不提供违法建议，不泄露他人隐私"
            />
          </el-form-item>

          <el-form-item label="System Prompt 模板">
            <el-input
              v-model="form.system_prompt_template"
              type="textarea"
              :autosize="{ minRows: 8, maxRows: 16 }"
              placeholder="留空使用内置默认模板；可用占位符：{name} {description} {personality} {speaking_style} {background} {hobbies} {social_circle} {taboos} {red_lines}"
            />
          </el-form-item>

          <el-divider content-position="left">后台可配置参数</el-divider>
          <p class="muted small">活泼闲聊模式与温柔倾听模式会根据语境自动切换，无需手动指令。</p>
          <p class="muted small">频率表示表达倾向；每条回复最多一个表情，回复字数受长度限制。</p>
          <div class="form-grid">
            <el-form-item label="人设风格切换">
              <el-select v-model="form.style_settings.style">
                <el-option label="活泼亲近" value="lively" />
                <el-option label="温柔安静" value="gentle" />
                <el-option label="清冷理智" value="cool" />
              </el-select>
            </el-form-item>
            <el-form-item label="活泼度倍率（0~100%）">
              <el-input-number v-model="form.style_settings.liveliness" :min="0" :max="100" :precision="0" aria-label="活泼度倍率（%）" />
            </el-form-item>
            <el-form-item label="表情出现频率">
              <div class="parameter-control">
                <el-input-number v-model="form.style_settings.emoji_frequency" :min="0" :max="100" :precision="0" aria-label="表情出现频率（%）" />
                <span class="muted">%</span>
              </div>
            </el-form-item>
            <el-form-item label="主动唤起记忆频率">
              <div class="parameter-control">
                <el-input-number v-model="form.style_settings.memory_recall_frequency" :min="0" :max="100" :precision="0" aria-label="主动唤起记忆频率（%）" />
                <span class="muted">%</span>
              </div>
            </el-form-item>
            <el-form-item label="回复目标长度">
              <div class="parameter-control">
                <el-input-number v-model="form.style_settings.reply_max_chars" :min="20" :max="2000" :precision="0" aria-label="回复目标长度（字，保留完整句子）" />
                <span class="muted">字</span>
              </div>
            </el-form-item>
            <el-form-item label="情绪共情强度">
              <div class="parameter-control">
                <el-input-number v-model="form.style_settings.empathy" :min="0" :max="100" :precision="0" aria-label="情绪共情强度（%）" />
                <span class="muted">%</span>
              </div>
            </el-form-item>
            <el-form-item label="自主表达倾向">
              <div class="parameter-control">
                <el-input-number v-model="form.style_settings.initiative" :min="0" :max="100" :precision="0" aria-label="自主表达倾向（%）" />
                <span class="muted">%</span>
              </div>
            </el-form-item>
            <el-form-item label="冷场自动兜底话题开关">
              <el-switch v-model="form.style_settings.topic_fallback" aria-label="冷场自动兜底话题开关" />
            </el-form-item>
          </div>

          <div class="form-grid">
            <el-form-item label="表情键">
              <el-input
                v-model="form.emoji_keys"
                placeholder="逗号分隔，例如：happy, shy, angry"
              />
            </el-form-item>
            <el-form-item label="启用 / 默认">
              <div class="switch-group">
                <div class="switch-item">
                  <el-switch v-model="form.enabled" />
                  <span>启用</span>
                </div>
                <div class="switch-item">
                  <el-switch v-model="form.is_default" />
                  <span>设为默认</span>
                </div>
              </div>
            </el-form-item>
          </div>
        </el-form>
      </el-scrollbar>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCharacter">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="previewVisible"
      :title="previewTitle"
      width="680px"
      top="6vh"
    >
      <div v-if="previewData" class="preview-body">
        <p class="muted small">以下是实际用于生成回复的完整 System Prompt。</p>
        <pre class="prompt-pre">{{ previewData.system_prompt }}</pre>
      </div>
      <div v-else class="yx-empty">正在生成 System Prompt…</div>
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :icon="DocumentCopy"
          :disabled="!previewData"
          @click="copyPrompt"
        >
          复制
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="importVisible"
      title="导入人设"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="粘贴从「导出」获得的人设 JSON，或其他人设模板内容"
        type="info"
        :closable="false"
        show-icon
      />
      <el-input
        v-model="importText"
        class="import-input"
        type="textarea"
        :rows="12"
        placeholder='{"name": "小满", "description": "温和陪伴、记性很好的朋友", "personality": "..."}'
      />
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="confirmImport">
          导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Delete,
  DocumentCopy,
  Download,
  Edit,
  Plus,
  Search,
  Star,
  Upload,
  View,
} from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import {
  createCharacter,
  deleteCharacter,
  exportCharacter,
  importCharacter,
  listCharacters,
  previewCharacter,
  setDefaultCharacter,
  updateCharacter,
} from '@/api/character'
import { formatDateTime } from '@/utils/format'

const SCOPE_LABELS = { all: '全部', private: '私聊', group: '群聊' }
const scopeOptions = [
  { value: 'all', label: '全部' },
  { value: 'private', label: '私聊' },
  { value: 'group', label: '群聊' },
]

const characters = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)

const dialogVisible = ref(false)
const editId = ref('')
const saving = ref(false)
const characterFormRef = ref(null)
const defaultingId = ref('')
const previewingId = ref('')
const exportingId = ref('')
const deletingId = ref('')

const previewVisible = ref(false)
const previewData = ref(null)
const importVisible = ref(false)
const importText = ref('')
const importing = ref(false)

const characterRules = {
  name: [{ required: true, message: '请输入人设名称', trigger: 'blur' }],
  scope: [{ required: true, message: '请选择生效范围', trigger: 'change' }],
}

function defaultSchedule() {
  return [
    { start: '00:00', end: '07:30', activity: '在睡觉' },
    { start: '07:30', end: '08:30', activity: '刚起床，洗漱吃早饭' },
    { start: '08:30', end: '12:00', activity: '在忙自己的事' },
    { start: '12:00', end: '14:00', activity: '吃完午饭，刷手机消食' },
    { start: '14:00', end: '18:00', activity: '在忙下午的事' },
    { start: '18:00', end: '19:30', activity: '吃晚饭，看看视频' },
    { start: '19:30', end: '23:00', activity: '晚上的自由时间，追剧打游戏' },
    { start: '23:00', end: '24:00', activity: '躺床上刷手机，准备睡了' },
  ]
}

function defaultForm() {
  return {
    name: '',
    scope: 'all',
    description: '',
    personality: '',
    speaking_style: '',
    background: '',
    hobbies: '',
    social_circle: '',
    life_schedule: defaultSchedule(),
    taboos: '',
    red_lines: '',
    system_prompt_template: '',
    style_settings: {
      style: 'lively',
      liveliness: 80,
      emoji_frequency: 30,
      memory_recall_frequency: 50,
      reply_max_chars: 300,
      topic_fallback: true,
      empathy: 80,
      initiative: 40,
    },
    emoji_keys: '',
    enabled: true,
    is_default: false,
  }
}

const form = reactive(defaultForm())

const emptyText = computed(() =>
  keyword.value.trim()
    ? '没有找到匹配的人设，试试其他关键词'
    : '还没有人设，点击右上角「新建人设」创建第一位角色',
)

const previewTitle = computed(() =>
  previewData.value ? `完整人设 · ${previewData.value.name}` : '完整人设预览',
)

function scopeLabel(scope) {
  return SCOPE_LABELS[scope] || '全部'
}

function scopeTagType(scope) {
  return { all: 'primary', private: 'warning', group: 'success' }[scope] || 'info'
}

async function load() {
  loading.value = true
  try {
    const data = await listCharacters({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined,
    })
    characters.value = data?.items || []
    total.value = data?.total || 0
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function handlePageChange(value) {
  page.value = value
  load()
}

function openCreate() {
  editId.value = ''
  Object.assign(form, defaultForm())
  dialogVisible.value = true
  nextTick(() => characterFormRef.value?.clearValidate())
}

function openEdit(item) {
  editId.value = item.id
  Object.assign(form, {
    name: item.name || '',
    scope: item.scope || 'all',
    description: item.description || '',
    personality: item.personality || '',
    speaking_style: item.speaking_style || '',
    background: item.background || '',
    hobbies: item.hobbies || '',
    social_circle: item.social_circle || '',
    life_schedule:
      Array.isArray(item.life_schedule) && item.life_schedule.length
        ? item.life_schedule.map((slot) => ({ ...slot }))
        : defaultSchedule(),
    taboos: item.taboos || '',
    red_lines: item.red_lines || '',
    system_prompt_template: item.system_prompt_template || '',
    style_settings: { ...defaultForm().style_settings, ...item.style_settings },
    emoji_keys: Array.isArray(item.emoji_keys) ? item.emoji_keys.join(', ') : '',
    enabled: item.enabled !== false,
    is_default: !!item.is_default,
  })
  dialogVisible.value = true
  nextTick(() => characterFormRef.value?.clearValidate())
}

function addScheduleSlot() {
  const last = form.life_schedule[form.life_schedule.length - 1]
  form.life_schedule.push({ start: last?.end || '08:00', end: '24:00', activity: '' })
}

async function saveCharacter() {
  try {
    await characterFormRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      scope: form.scope,
      description: form.description.trim(),
      personality: form.personality.trim(),
      speaking_style: form.speaking_style.trim(),
      background: form.background.trim(),
      hobbies: form.hobbies.trim(),
      social_circle: form.social_circle.trim(),
      life_schedule: form.life_schedule
        .map((slot) => ({
          start: (slot.start || '').trim(),
          end: (slot.end || '').trim(),
          activity: (slot.activity || '').trim(),
        }))
        .filter((slot) => slot.start || slot.end || slot.activity),
      taboos: form.taboos.trim(),
      red_lines: form.red_lines.trim(),
      system_prompt_template: form.system_prompt_template.trim(),
      style_settings: { ...form.style_settings },
      emoji_keys: form.emoji_keys
        .split(/[,，]/)
        .map((key) => key.trim())
        .filter(Boolean),
      enabled: form.enabled,
      is_default: form.is_default,
    }

    if (editId.value) {
      await updateCharacter(editId.value, payload)
      ElMessage.success('人设已更新')
    } else {
      await createCharacter(payload)
      ElMessage.success('人设已创建')
      page.value = 1
    }
    dialogVisible.value = false
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    saving.value = false
  }
}

async function makeDefault(item) {
  defaultingId.value = item.id
  try {
    await setDefaultCharacter(item.id)
    ElMessage.success(`已将「${item.name}」设为默认人设`)
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    defaultingId.value = ''
  }
}

async function openPreview(item) {
  previewingId.value = item.id
  previewData.value = null
  previewVisible.value = true
  try {
    previewData.value = await previewCharacter(item.id)
  } catch {
    previewVisible.value = false
  } finally {
    previewingId.value = ''
  }
}

async function copyPrompt() {
  const text = previewData.value?.system_prompt || ''
  if (!text) return
  if (!navigator.clipboard) {
    ElMessage.warning('当前环境不支持自动复制，请手动选择文本复制')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本复制')
  }
}

async function exportItem(item) {
  exportingId.value = item.id
  try {
    const data = await exportCharacter(item.id)
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${(item.name || 'character').replace(/[\\/:*?"<>|]/g, '_')}.character.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    ElMessage.success('人设已导出')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    exportingId.value = ''
  }
}

async function removeItem(item) {
  if (item.is_default) {
    ElMessage.warning('默认人设不能删除，请先切换默认人设')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定删除人设「${item.name}」吗？此操作不可恢复。`,
      '删除人设',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  deletingId.value = item.id
  try {
    await deleteCharacter(item.id)
    ElMessage.success('人设已删除')
    if (characters.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch {
    // 默认人设会被后端拒绝（409），错误提示由请求拦截器统一展示
  } finally {
    deletingId.value = ''
  }
}

function openImport() {
  importText.value = ''
  importVisible.value = true
}

async function confirmImport() {
  if (!importText.value.trim()) {
    ElMessage.warning('请先粘贴人设 JSON')
    return
  }
  let data
  try {
    data = JSON.parse(importText.value)
  } catch {
    ElMessage.error('JSON 格式错误，请检查后重试')
    return
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    ElMessage.error('JSON 格式错误：应为对象结构')
    return
  }
  importing.value = true
  try {
    await importCharacter(data)
    ElMessage.success('人设导入成功')
    importVisible.value = false
    importText.value = ''
    page.value = 1
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    importing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.search-card {
  padding: 16px 20px;
}

.search-toolbar {
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom: 0;
}

.search-input { width: 320px; max-width: 100%; }

.char-list {
  min-height: 160px;
}

.char-list .yx-grid {
  align-items: stretch;
}

.char-card {
  display: flex;
  flex-direction: column;
  transition: border-color 0.16s ease;
}

.char-card:hover, .char-card:focus-within {
  border-color: var(--el-color-primary-light-5);
}

.char-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.char-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--yx-text);
  word-break: break-word;
}

.char-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.char-desc {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
  margin: 12px 0 0;
  min-height: 42px;
  color: var(--yx-text-2);
  font-size: 13px;
  line-height: 1.65;
  word-break: break-word;
}

.char-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: auto;
  padding-top: 14px;
}

.char-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--yx-line);
}

.char-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.form-grid :deep(.el-select) { width: 100%; }
.form-grid :deep(.el-form-item) { min-width: 0; }

.switch-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
  min-height: 32px;
}

.switch-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--yx-text-2);
}

.parameter-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.schedule-editor {
  width: 100%;
}

.schedule-hint { margin: 4px 0 8px; }

.schedule-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.schedule-time {
  width: 110px;
  flex-shrink: 0;
}

.schedule-sep {
  flex-shrink: 0;
  font-size: 13px;
  color: var(--yx-text-2);
}

.schedule-activity {
  flex: 1;
  min-width: 0;
}

.prompt-pre {
  margin: 0;
  max-height: 52vh;
  overflow: auto;
  padding: 16px;
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

.import-input {
  margin-top: 12px;
}

@media (max-width: 700px) {
  .search-card { padding: 16px; }
  .search-input { flex: 1; min-width: 150px; }
  .search-toolbar .yx-toolbar-spacer { display: none; }
  .search-toolbar > .muted { flex-basis: 100%; }
  .form-grid {
    grid-template-columns: 1fr;
  }
  .schedule-row { flex-wrap: wrap; padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid var(--yx-line); }
  .schedule-time { flex: 1; min-width: 0; width: auto; }
  .schedule-activity { flex-basis: calc(100% - 48px); }
  .char-actions :deep(.el-button) { min-height: 36px; }
}
</style>
