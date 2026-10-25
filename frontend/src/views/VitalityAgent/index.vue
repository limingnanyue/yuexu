<template>
  <div class="yx-page vitality-page">
    <PageHeader title="活力 Agent" description="会话静默后主动搭话：无聊分 + 动态阈值自适应">
      <el-tag :type="settings.enabled ? 'success' : 'info'" effect="plain" size="small">
        {{ settings.enabled ? '已启用' : '已停用' }}
      </el-tag>
      <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
    </PageHeader>

    <div class="yx-hint">
      会话越安静无聊分越高，达到该会话的动态阈值时主动搭一句；用户回复热情阈值自动下调（更容易触发）、
      回复冷淡自动上调（更难触发），并受冷却、每小时上限与活跃时段约束。账号管理里可单独关闭某个机器人的活力搭话。
    </div>

    <el-tabs v-model="activeTab" class="vitality-tabs">
      <!-- ======================= 全局设置（能力范围） ======================= -->
      <el-tab-pane label="能力范围" name="settings">
        <el-alert
          v-if="!auth.isOwner"
          title="仅超级主人可修改全局参数，当前页面为只读模式"
          type="warning"
          show-icon
          :closable="false"
        />
        <section class="yx-card">
          <el-form :model="settings" label-position="top" :disabled="!auth.isOwner" @submit.prevent="saveSettings">
            <section class="form-section" aria-labelledby="vit-basic-title">
              <div class="section-heading">
                <h4 id="vit-basic-title">总开关</h4>
                <p>关闭后轮询停止，所有会话都不再主动搭话。</p>
              </div>
              <el-form-item label="启用活力 Agent">
                <div class="switch-line">
                  <el-switch v-model="settings.enabled" />
                  <span class="muted small">对话消息仍会记录活跃度，只是不主动发送</span>
                </div>
              </el-form-item>
            </section>

            <section class="form-section" aria-labelledby="vit-threshold-title">
              <div class="section-heading">
                <h4 id="vit-threshold-title">无聊分与自适应阈值</h4>
                <p>新会话从基础阈值开始；用户热情 / 冷淡会让阈值在锁死区间内自动下调 / 上调。</p>
              </div>
              <div class="form-grid">
                <el-form-item label="基础阈值（0-100）">
                  <el-slider
                    class="threshold-slider"
                    v-model="settings.base_threshold"
                    show-input
                    :min="0"
                    :max="100"
                    :marks="{ 40: '低', 60: '默认', 90: '高' }"
                  />
                </el-form-item>
                <div class="threshold-pair">
                  <el-form-item label="阈值下限">
                    <el-input-number v-model="settings.threshold_min" :min="0" :max="100" controls-position="right" style="width: 100%" />
                  </el-form-item>
                  <el-form-item label="阈值上限">
                    <el-input-number v-model="settings.threshold_max" :min="1" :max="100" controls-position="right" style="width: 100%" />
                  </el-form-item>
                </div>
              </div>
            </section>

            <section class="form-section" aria-labelledby="vit-scope-title">
              <div class="section-heading">
                <h4 id="vit-scope-title">打扰范围</h4>
                <p>控制主动搭话的频率与时段，避免过度打扰。</p>
              </div>
              <div class="form-grid">
                <el-form-item label="私聊冷却（分钟）">
                  <el-input-number v-model="settings.private_cooldown_minutes" :min="1" :max="1440" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="群聊冷却（分钟）">
                  <el-input-number v-model="settings.group_cooldown_minutes" :min="1" :max="1440" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="单会话每小时上限（次）">
                  <el-input-number v-model="settings.max_hour_sends" :min="1" :max="10" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="每轮轮询最多发送（个）">
                  <el-input-number v-model="settings.max_sends_per_tick" :min="1" :max="20" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="活跃时段">
                  <el-input v-model="settings.active_window" placeholder="09:00-23:00" />
                  <div class="field-hint">时段外不主动发消息，支持跨零点（如 22:00-07:00）</div>
                </el-form-item>
                <el-form-item label="无回复判定窗口（分钟）">
                  <el-input-number v-model="settings.reply_window_minutes" :min="5" :max="1440" controls-position="right" style="width: 100%" />
                </el-form-item>
                <el-form-item label="轮询间隔（秒）">
                  <el-input-number v-model="settings.interval" :min="30" :max="3600" controls-position="right" style="width: 100%" />
                  <div class="field-hint">重启服务后生效</div>
                </el-form-item>
              </div>
            </section>
          </el-form>
          <div class="form-actions">
            <span class="muted small">保存后立即生效（轮询间隔除外）</span>
            <el-button type="primary" :loading="saving" :disabled="!auth.isOwner" @click="saveSettings">
              保存配置
            </el-button>
          </div>
        </section>
      </el-tab-pane>

      <!-- ======================= 会话 ======================= -->
      <el-tab-pane :label="`会话 (${sessionTotal})`" name="sessions">
        <section class="yx-card">
          <div class="table-toolbar">
            <el-select v-model="sessionFilter.target_type" aria-label="会话类型" placeholder="全部类型" clearable class="session-filter" @change="loadSessions(1)">
              <el-option label="私聊" value="private" />
              <el-option label="群聊" value="group" />
            </el-select>
            <el-select v-model="sessionFilter.enabled" aria-label="活力搭话状态" placeholder="全部状态" clearable class="session-filter" @change="loadSessions(1)">
              <el-option label="已开启" :value="true" />
              <el-option label="已关闭" :value="false" />
            </el-select>
            <el-button :icon="Refresh" @click="loadSessions()">刷新</el-button>
          </div>

          <el-table :data="sessions" v-loading="sessionLoading" row-key="id">
            <el-table-column label="会话" min-width="180">
              <template #default="{ row }">
                <div class="session-cell">
                  <el-tag :type="row.target_type === 'group' ? 'warning' : 'success'" effect="plain" size="small">
                    {{ row.target_type === 'group' ? '群' : '私聊' }}
                  </el-tag>
                  <span class="mono">{{ row.target_id }}</span>
                </div>
                <div v-if="row.bot_name" class="muted small">{{ row.bot_name }}</div>
                <div v-else class="muted small mono">{{ row.bot_id }}</div>
              </template>
            </el-table-column>
            <el-table-column label="无聊分 / 阈值" width="200">
              <template #default="{ row }">
                <el-progress
                  :percentage="Math.min(100, row.score)"
                  :color="row.score >= row.dynamic_threshold ? '#e6a23c' : undefined"
                  :stroke-width="10"
                />
                <span class="muted small">当前 {{ row.score }} / 阈值 {{ row.dynamic_threshold }}（{{ row.threshold_bounds?.[0] }}-{{ row.threshold_bounds?.[1] }}）</span>
              </template>
            </el-table-column>
            <el-table-column label="最近消息" width="150">
              <template #default="{ row }">{{ formatTime(row.last_msg_time) }}</template>
            </el-table-column>
            <el-table-column label="上次搭话" width="150">
              <template #default="{ row }">{{ formatTime(row.last_agent_send_time) }}</template>
            </el-table-column>
            <el-table-column label="连续冷淡" width="90" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.consecutive_cold_reply > 0" type="warning" effect="plain" size="small">
                  {{ row.consecutive_cold_reply }}
                </el-tag>
                <span v-else class="muted">0</span>
              </template>
            </el-table-column>
            <el-table-column label="开启" width="80" align="center">
              <template #default="{ row }">
                <el-switch v-model="row.enable_agent" :aria-label="`启用 ${row.target_id} 的活力搭话`" @change="patchSession(row, { enable_agent: row.enable_agent })" />
              </template>
            </el-table-column>
            <el-table-column label="黑名单" width="80" align="center">
              <template #default="{ row }">
                <el-switch v-model="row.is_black" :aria-label="`将 ${row.target_id} 加入黑名单`" @change="patchSession(row, { is_black: row.is_black })" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="170" align="center">
              <template #default="{ row }">
                <el-button size="small" :loading="previewLoading === row.id" @click="runPreview(row)">预览</el-button>
                <el-button size="small" @click="openThreshold(row)">调阈值</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无会话，收到对话消息后会在这里显示" :image-size="80" /></template>
          </el-table>
          <el-pagination
            v-if="sessionTotal > sessionFilter.page_size"
            layout="total, prev, pager, next"
            :total="sessionTotal"
            :page-size="sessionFilter.page_size"
            :current-page="sessionFilter.page"
            @current-change="loadSessions"
            style="margin-top: 16px; justify-content: flex-end"
          />
        </section>
      </el-tab-pane>

      <!-- ======================= 活力日志 ======================= -->
      <el-tab-pane label="活力日志" name="logs">
        <section class="yx-card">
          <div class="table-toolbar">
            <el-select v-model="logFilter.status" aria-label="活力日志状态" placeholder="全部状态" clearable class="log-filter" @change="loadLogs(1)">
              <el-option label="发送成功" value="success" />
              <el-option label="冷却拦截" value="reject_cooling" />
              <el-option label="黑名单拦截" value="reject_black" />
              <el-option label="次数上限" value="reject_limit" />
              <el-option label="内容校验不过" value="reject_validate" />
              <el-option label="发送失败" value="failed" />
            </el-select>
            <el-button :icon="Refresh" @click="loadLogs()">刷新</el-button>
          </div>
          <el-table :data="logs" v-loading="logLoading" row-key="id">
            <el-table-column label="时间" width="150">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="会话" min-width="140">
              <template #default="{ row }">
                <el-tag :type="row.target_type === 'group' ? 'warning' : 'success'" effect="plain" size="small">
                  {{ row.target_type === 'group' ? '群' : '私聊' }}
                </el-tag>
                <span class="mono small">{{ row.target_id }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" effect="plain" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="触发原因" width="100">
              <template #default="{ row }">{{ row.trigger_reason || '—' }}</template>
            </el-table-column>
            <el-table-column label="无聊分" width="70" align="center">
              <template #default="{ row }">{{ row.score }}</template>
            </el-table-column>
            <el-table-column label="搭话内容 / 拒绝原因" min-width="200">
              <template #default="{ row }">{{ row.status === 'success' ? row.content : (row.reject_msg || '—') }}</template>
            </el-table-column>
            <el-table-column label="用户回复" min-width="160">
              <template #default="{ row }">
                <template v-if="row.user_reply_sentiment">
                  <el-tag
                    :type="row.user_reply_sentiment === 'hot' ? 'success' : row.user_reply_sentiment === 'cold' ? 'info' : 'warning'"
                    effect="plain"
                    size="small"
                  >
                    {{ sentimentLabel(row.user_reply_sentiment) }}
                  </el-tag>
                  <span v-if="row.user_reply" class="small">{{ row.user_reply }}</span>
                </template>
                <span v-else class="muted">未回填</span>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无活力日志" :image-size="80" /></template>
          </el-table>
          <el-pagination
            v-if="logTotal > logFilter.page_size"
            layout="total, prev, pager, next"
            :total="logTotal"
            :page-size="logFilter.page_size"
            :current-page="logFilter.page"
            @current-change="loadLogs"
            style="margin-top: 16px; justify-content: flex-end"
          />
        </section>
      </el-tab-pane>

      <!-- ======================= 话题素材 ======================= -->
      <el-tab-pane :label="`话题素材 (${topics.length})`" name="topics">
        <section class="yx-card">
          <el-form :model="topicForm" label-position="top" :disabled="!auth.isOwner" @submit.prevent="addTopic">
            <div class="topic-form">
              <el-form-item label="话题内容" class="grow">
                <el-input v-model="topicForm.topic_content" maxlength="200" show-word-limit placeholder="例如：最近有没有发现什么有意思的小事呀？" />
              </el-form-item>
              <el-form-item label="标签" class="topic-tag">
                <el-select v-model="topicForm.tag">
                  <el-option label="普通 normal" value="normal" />
                  <el-option label="记忆 memory" value="memory" />
                  <el-option label="趣味 fun" value="fun" />
                  <el-option label="提问 question" value="question" />
                </el-select>
              </el-form-item>
              <el-form-item label="权重" class="topic-weight">
                <el-input-number v-model="topicForm.weight" :min="1" :max="100" controls-position="right" style="width: 100%" />
              </el-form-item>
              <el-form-item label=" " class="topic-add">
                <el-button type="primary" :loading="topicSaving" @click="addTopic">添加</el-button>
              </el-form-item>
            </div>
          </el-form>

          <el-table :data="topics" v-loading="topicLoading" row-key="id">
            <el-table-column label="话题内容" min-width="280">
              <template #default="{ row }">
                <el-input v-if="editingTopic === row.id" v-model="editForm.topic_content" maxlength="200" />
                <span v-else>{{ row.topic_content }}</span>
              </template>
            </el-table-column>
            <el-table-column label="标签" width="120">
              <template #default="{ row }">
                <el-select v-if="editingTopic === row.id" v-model="editForm.tag" size="small">
                  <el-option label="normal" value="normal" />
                  <el-option label="memory" value="memory" />
                  <el-option label="fun" value="fun" />
                  <el-option label="question" value="question" />
                </el-select>
                <el-tag v-else effect="plain" size="small">{{ row.tag }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="权重" width="150">
              <template #default="{ row }">
                <el-input-number
                  v-if="editingTopic === row.id"
                  v-model="editForm.weight"
                  :min="1"
                  :max="100"
                  size="small"
                  controls-position="right"
                  style="width: 100%"
                />
                <span v-else>{{ row.weight }}</span>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="80" align="center">
              <template #default="{ row }">
                <el-switch v-model="row.enable" :aria-label="`启用话题 ${row.topic_content}`" :disabled="!auth.isOwner" @change="saveTopic(row, { enable: row.enable })" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" align="center">
              <template #default="{ row }">
                <template v-if="editingTopic === row.id">
                  <el-button size="small" type="primary" @click="confirmEdit(row)">保存</el-button>
                  <el-button size="small" @click="editingTopic = null">取消</el-button>
                </template>
                <template v-else>
                  <el-button size="small" :disabled="!auth.isOwner" @click="startEdit(row)">编辑</el-button>
                  <el-button size="small" type="danger" plain :disabled="!auth.isOwner" @click="removeTopic(row)">删除</el-button>
                </template>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无话题素材，可在上方添加" :image-size="80" /></template>
          </el-table>
          <div class="yx-hint" style="margin-top: 12px">
            素材只在「记忆延伸」和「上下文延伸」都没有可用材料时才会兜底使用，权重越大越容易被抽中。
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>

    <!-- 预览结果 -->
    <el-dialog v-model="previewVisible" title="预览主动搭话（不会发送）" width="520px">
      <div v-if="previewResult" v-loading="previewLoading === 'dialog'">
        <div class="result-meta">
          <el-tag effect="plain" size="small">{{ previewResult.trigger_reason }}</el-tag>
          <span class="muted small">无聊分 {{ previewResult.score }} / 阈值 {{ previewResult.dynamic_threshold }}</span>
        </div>
        <el-alert
          v-if="previewResult.error"
          :title="previewResult.error"
          type="warning"
          show-icon
          :closable="false"
          style="margin-top: 12px"
        />
        <div v-if="previewResult.content" class="summary-text" style="margin-top: 12px">{{ previewResult.content }}</div>
      </div>
    </el-dialog>

    <!-- 调阈值 -->
    <el-dialog v-model="thresholdVisible" title="调整会话阈值" width="420px">
      <p class="muted small" style="margin-top: 0">
        手动覆盖该会话的动态阈值（下次自适应仍会在此基础上增减）。范围 {{ thresholdBounds[0] }}-{{ thresholdBounds[1] }}。
      </p>
      <el-slider v-model="thresholdValue" class="threshold-slider" show-input :min="thresholdBounds[0]" :max="thresholdBounds[1]" />
      <template #footer>
        <el-button @click="thresholdVisible = false">取消</el-button>
        <el-button type="primary" @click="saveThreshold">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import {
  createTopic,
  deleteTopic,
  getVitalitySettings,
  listTopics,
  listVitalityLogs,
  listVitalitySessions,
  patchVitalitySession,
  previewVitality,
  updateTopic,
  updateVitalitySettings,
} from '@/api/vitality'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const activeTab = ref('settings')

// ---------------- 全局设置 ----------------
const settings = reactive({
  enabled: false,
  interval: 60,
  base_threshold: 60,
  threshold_min: 40,
  threshold_max: 90,
  private_cooldown_minutes: 45,
  group_cooldown_minutes: 120,
  max_hour_sends: 2,
  active_window: '09:00-23:00',
  reply_window_minutes: 60,
  max_sends_per_tick: 3,
})

function applySettings(data) {
  for (const key of Object.keys(settings)) {
    if (data[key] !== undefined && data[key] !== null) settings[key] = data[key]
  }
}

async function saveSettings() {
  if (!auth.isOwner) return
  if (settings.threshold_min >= settings.threshold_max) {
    ElMessage.warning('阈值下限必须小于上限')
    return
  }
  saving.value = true
  try {
    await updateVitalitySettings({ ...settings })
    ElMessage.success('活力 Agent 配置已保存')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    saving.value = false
  }
}

// ---------------- 会话 ----------------
const sessions = ref([])
const sessionTotal = ref(0)
const sessionLoading = ref(false)
const sessionFilter = reactive({ page: 1, page_size: 20, target_type: null, enabled: null })

async function loadSessions(page = sessionFilter.page) {
  sessionFilter.page = page
  sessionLoading.value = true
  try {
    const params = { page, page_size: sessionFilter.page_size }
    if (sessionFilter.target_type) params.target_type = sessionFilter.target_type
    if (sessionFilter.enabled !== null && sessionFilter.enabled !== '') params.enabled = sessionFilter.enabled
    const data = await listVitalitySessions(params)
    sessions.value = data.items || []
    sessionTotal.value = data.total || 0
  } catch {
    // 请求拦截器已提示
  } finally {
    sessionLoading.value = false
  }
}

async function patchSession(row, payload) {
  try {
    const data = await patchVitalitySession(row.id, payload)
    Object.assign(row, data)
    ElMessage.success('已保存')
  } catch {
    await loadSessions()
  }
}

const thresholdBounds = computed(() => sessions.value[0]?.threshold_bounds || [40, 90])
const thresholdVisible = ref(false)
const thresholdValue = ref(60)
let thresholdRow = null

function openThreshold(row) {
  thresholdRow = row
  thresholdValue.value = row.dynamic_threshold
  thresholdVisible.value = true
}

async function saveThreshold() {
  if (!thresholdRow) return
  await patchSession(thresholdRow, { dynamic_threshold: thresholdValue.value })
  thresholdVisible.value = false
}

// ---------------- 预览 ----------------
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewResult = ref(null)

async function runPreview(row) {
  previewLoading.value = row.id
  previewResult.value = null
  try {
    previewResult.value = await previewVitality({
      bot_id: row.bot_id,
      target_type: row.target_type,
      target_id: row.target_id,
    })
    previewVisible.value = true
  } catch {
    // 请求拦截器已提示
  } finally {
    previewLoading.value = false
  }
}

// ---------------- 日志 ----------------
const logs = ref([])
const logTotal = ref(0)
const logLoading = ref(false)
const logFilter = reactive({ page: 1, page_size: 20, status: null })

const STATUS_LABELS = {
  success: '发送成功',
  reject_cooling: '冷却拦截',
  reject_black: '黑名单拦截',
  reject_limit: '次数上限',
  reject_score_low: '分数不足',
  reject_validate: '校验不过',
  reject_window: '时段限制',
  failed: '发送失败',
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

function statusType(status) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  return 'info'
}

function sentimentLabel(sentiment) {
  return { hot: '热情', cold: '冷淡', none: '未回复' }[sentiment] || sentiment
}

async function loadLogs(page = logFilter.page) {
  logFilter.page = page
  logLoading.value = true
  try {
    const params = { page, page_size: logFilter.page_size }
    if (logFilter.status) params.status = logFilter.status
    const data = await listVitalityLogs(params)
    logs.value = data.items || []
    logTotal.value = data.total || 0
  } catch {
    // 请求拦截器已提示
  } finally {
    logLoading.value = false
  }
}

// ---------------- 话题素材 ----------------
const topics = ref([])
const topicLoading = ref(false)
const topicSaving = ref(false)
const topicForm = reactive({ topic_content: '', tag: 'normal', weight: 10 })
const editingTopic = ref(null)
const editForm = reactive({ topic_content: '', tag: 'normal', weight: 10 })

async function loadTopics() {
  topicLoading.value = true
  try {
    const data = await listTopics()
    topics.value = data.items || []
  } catch {
    // 请求拦截器已提示
  } finally {
    topicLoading.value = false
  }
}

async function addTopic() {
  const content = topicForm.topic_content.trim()
  if (!content) {
    ElMessage.warning('请输入话题内容')
    return
  }
  topicSaving.value = true
  try {
    await createTopic({ ...topicForm, topic_content: content })
    topicForm.topic_content = ''
    ElMessage.success('素材已添加')
    await loadTopics()
  } catch {
    // 请求拦截器已提示
  } finally {
    topicSaving.value = false
  }
}

function startEdit(row) {
  editingTopic.value = row.id
  Object.assign(editForm, {
    topic_content: row.topic_content,
    tag: row.tag,
    weight: row.weight,
  })
}

async function confirmEdit(row) {
  try {
    const data = await updateTopic(row.id, { ...editForm, enable: row.enable })
    Object.assign(row, data.topic)
    editingTopic.value = null
    ElMessage.success('已保存')
  } catch {
    // 请求拦截器已提示
  }
}

async function saveTopic(row, payload) {
  try {
    await updateTopic(row.id, {
      topic_content: row.topic_content,
      tag: row.tag,
      weight: row.weight,
      enable: row.enable,
      ...payload,
    })
    ElMessage.success('已保存')
  } catch {
    await loadTopics()
  }
}

async function removeTopic(row) {
  try {
    await ElMessageBox.confirm(`删除素材「${row.topic_content.slice(0, 30)}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteTopic(row.id)
    ElMessage.success('已删除')
    await loadTopics()
  } catch {
    // 请求拦截器已提示
  }
}

// ---------------- 公共 ----------------
function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

async function loadAll() {
  loading.value = true
  try {
    applySettings(await getVitalitySettings())
  } catch {
    // 请求拦截器已提示
  } finally {
    loading.value = false
  }
  await Promise.all([loadSessions(1), loadLogs(1), loadTopics()])
}

onMounted(loadAll)
</script>

<style scoped>
.vitality-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.vitality-tabs :deep(.el-alert) { margin-bottom: 16px; }
.vitality-tabs :deep(.el-tab-pane) { min-width: 0; }
.vitality-page :deep(.el-slider__marks-text) { font-size: 12px; }

.form-section + .form-section {
  margin-top: 20px;
  padding-top: 28px;
  border-top: 1px solid var(--yx-line);
}

.section-heading {
  margin-bottom: 20px;
}

.section-heading h4 {
  margin: 0 0 4px;
  color: var(--yx-text);
  font-size: 15px;
  font-weight: 600;
}

.section-heading p {
  margin: 0;
  color: var(--yx-muted);
  font-size: 12px;
  line-height: 1.7;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 24px;
}

.threshold-pair {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.switch-line {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-height: 32px;
}

.switch-line .el-switch {
  flex: none;
}

.switch-line .small {
  padding-top: 6px;
}

.field-hint {
  margin-top: 4px;
  color: var(--yx-muted);
  font-size: 12px;
  line-height: 1.6;
}

.form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--yx-line);
}

.table-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--yx-line);
}

.session-filter { width: 140px; }
.log-filter { width: 200px; }

.session-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.topic-form {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 140px 120px auto;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 8px;
}

.topic-form .grow {
  min-width: 0;
}

.topic-form .el-select { width: 100%; }

.result-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.summary-text {
  padding: 14px 16px;
  border: 1px solid var(--yx-line);
  border-radius: 12px;
  background: var(--yx-elevated);
  color: var(--yx-text-2);
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 760px) {
  .form-grid,
  .threshold-pair {
    grid-template-columns: 1fr;
  }
  .table-toolbar .session-filter { flex: 1; min-width: 110px; }
  .table-toolbar .log-filter { width: 100%; }
  .topic-form { grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 0 12px; }
  .topic-form .grow { grid-column: 1 / -1; }
  .topic-add { grid-column: 1 / -1; }
  .topic-add :deep(.el-form-item__label) { display: none; }
  .topic-add .el-button { width: 100%; }
  .threshold-slider { flex-wrap: wrap; height: auto; }
  .threshold-slider :deep(.el-slider__runway) { flex-basis: 100%; margin: 16px 8px 30px; }
  .threshold-slider :deep(.el-slider__input) { width: 100%; margin: 0 0 16px; }
}
</style>
