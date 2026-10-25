<template>
  <div class="yx-page">
    <PageHeader title="日志" description="消息 / AI / 搜索 / 推送 / 操作日志">
      <span v-if="!loading" class="muted small">共 {{ total }} 条</span>
      <el-button
        v-if="auth.isOwner"
        type="danger"
        plain
        :icon="Delete"
        @click="openCleanup"
      >
        清理日志
      </el-button>
    </PageHeader>

    <div class="yx-card log-panel">
      <el-tabs v-model="activeType" class="log-tabs" @tab-change="handleTabChange">
        <el-tab-pane
          v-for="tab in tabs"
          :key="tab.name"
          :label="tab.label"
          :name="tab.name"
        />
      </el-tabs>

      <p v-if="activeType === 'ai'" class="muted small">Tokens 为接口返回的用量，未返回用量时记为 0。</p>

      <div class="yx-toolbar log-filters">
        <el-input
          v-model="keyword"
          aria-label="日志关键词"
          placeholder="关键词（内容 / 用户 / 动作）"
          clearable
          class="log-keyword"
          :prefix-icon="Search"
          @keyup.enter="search"
        />
        <el-date-picker
          v-model="dateRange"
          aria-label="日志时间范围"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DDTHH:mm:ss"
          :default-time="defaultTime"
          class="log-date-range"
        />
        <el-button type="primary" :icon="Search" :loading="loading" @click="search">
          查询
        </el-button>
        <el-button :icon="RefreshLeft" @click="reset">重置</el-button>
        <span class="yx-toolbar-spacer"></span>
        <el-button :icon="Download" :loading="exporting" @click="exportCsv">
          导出 CSV
        </el-button>
      </div>

      <el-table
        :key="activeType"
        v-loading="loading"
        :data="rows"
        row-key="id"
        style="width: 100%"
      >
        <el-table-column label="时间" width="168">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>

        <template v-if="activeType === 'message'">
          <el-table-column label="方向" width="80">
            <template #default="{ row }">
              <el-tag
                size="small"
                effect="plain"
                :type="row.direction === 'in' ? 'info' : 'success'"
              >
                {{ row.direction === 'in' ? '接收' : '发送' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="场景" width="80">
            <template #default="{ row }">{{ sceneLabel(row.scene) }}</template>
          </el-table-column>
          <el-table-column label="群号" width="120" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.group_id || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="用户" width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ row.nickname || row.user_id || '-' }}</template>
          </el-table-column>
          <el-table-column label="内容" min-width="260">
            <template #default="{ row }">
              <button type="button"
                v-if="row.content"
                class="cell-link"
                :title="row.content"
                @click="openDetail(row)"
              >
                {{ truncate(row.content, 46) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="logStatusType(row.status)">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="错误" width="160">
            <template #default="{ row }">
              <button type="button"
                v-if="row.error"
                class="cell-link yx-danger-text"
                :title="row.error"
                @click="openDetail(row)"
              >
                {{ truncate(row.error, 24) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
        </template>

        <template v-else-if="activeType === 'ai'">
          <el-table-column label="模型" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ row.model_name || row.model_id || '-' }}</template>
          </el-table-column>
          <el-table-column label="场景" width="80">
            <template #default="{ row }">{{ sceneLabel(row.scene) }}</template>
          </el-table-column>
          <el-table-column label="Tokens" min-width="190">
            <template #default="{ row }">
              <div class="mono">{{ ((row.prompt_tokens ?? 0) + (row.completion_tokens ?? 0)).toLocaleString('zh-CN') }}</div>
              <div class="muted small">输入 {{ (row.prompt_tokens ?? 0).toLocaleString('zh-CN') }} / 输出 {{ (row.completion_tokens ?? 0).toLocaleString('zh-CN') }}</div>
            </template>
          </el-table-column>
          <el-table-column label="延迟" width="90">
            <template #default="{ row }">
              <span class="mono">{{ row.latency_ms ?? 0 }} ms</span>
            </template>
          </el-table-column>
          <el-table-column label="输入" min-width="220">
            <template #default="{ row }">
              <button type="button"
                v-if="row.prompt_preview"
                class="cell-link"
                :title="row.prompt_preview"
                @click="openDetail(row)"
              >
                {{ truncate(row.prompt_preview, 40) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="输出" min-width="220">
            <template #default="{ row }">
              <button type="button"
                v-if="row.response_preview"
                class="cell-link"
                :title="row.response_preview"
                @click="openDetail(row)"
              >
                {{ truncate(row.response_preview, 40) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.success ? 'success' : 'danger'">
                {{ row.success ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="错误" width="160">
            <template #default="{ row }">
              <button type="button"
                v-if="row.error"
                class="cell-link yx-danger-text"
                :title="row.error"
                @click="openDetail(row)"
              >
                {{ truncate(row.error, 24) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
        </template>

        <template v-else-if="activeType === 'search'">
          <el-table-column label="查询" min-width="200">
            <template #default="{ row }">
              <button type="button"
                v-if="row.query"
                class="cell-link"
                :title="row.query"
                @click="openDetail(row)"
              >
                {{ truncate(row.query, 36) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="触发方式" width="100">
            <template #default="{ row }">
              <el-tag
                size="small"
                effect="plain"
                :type="row.trigger_mode === 'auto' ? 'warning' : 'info'"
              >
                {{ row.trigger_mode === 'auto' ? '自动' : '手动' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="结果数" width="80">
            <template #default="{ row }">{{ row.result_count ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">
              <span class="mono">{{ row.latency_ms ?? 0 }} ms</span>
            </template>
          </el-table-column>
          <el-table-column label="成功" width="80">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.success ? 'success' : 'danger'">
                {{ row.success ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="摘要" min-width="260">
            <template #default="{ row }">
              <button type="button"
                v-if="row.summary_preview"
                class="cell-link"
                :title="row.summary_preview"
                @click="openDetail(row)"
              >
                {{ truncate(row.summary_preview, 46) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
        </template>

        <template v-else-if="activeType === 'push'">
          <el-table-column label="任务 ID" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.task_id || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="目标" min-width="180">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">
                {{ row.target_type === 'group' ? '群聊' : '私聊' }}
              </el-tag>
              <span class="target-id mono">{{ row.target_id || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="成功" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="row.success ? 'success' : 'danger'">
                {{ row.success ? '成功' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="错误" min-width="260">
            <template #default="{ row }">
              <button type="button"
                v-if="row.error"
                class="cell-link yx-danger-text"
                :title="row.error"
                @click="openDetail(row)"
              >
                {{ truncate(row.error, 46) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
        </template>

        <template v-else-if="activeType === 'operation'">
          <el-table-column label="级别" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="levelType(row.level)">
                {{ levelLabel(row.level) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="模块" width="120" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.module || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="动作" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.action || '-' }}</template>
          </el-table-column>
          <el-table-column label="详情" min-width="300">
            <template #default="{ row }">
              <button type="button"
                v-if="row.detail"
                class="cell-link"
                :title="row.detail"
                @click="openDetail(row)"
              >
                {{ truncate(row.detail, 56) }}
              </button>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
        </template>

        <template #empty>
          <el-empty description="暂无日志" :image-size="90" />
        </template>
      </el-table>

      <el-pagination
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :total="total"
        background
        layout="total, sizes, prev, pager, next"
        @size-change="handleSizeChange"
        @current-change="handleCurrentChange"
      />
    </div>

    <el-dialog v-model="detailVisible" title="日志详情" width="640px" destroy-on-close>
      <el-descriptions v-if="detailRow" :column="1" border size="small" label-width="100px">
        <el-descriptions-item v-for="field in detailFields" :key="field.label" :label="field.label">
          <pre v-if="field.pre" class="detail-pre">{{ displayValue(field.value) }}</pre>
          <span v-else class="detail-value" :class="{ mono: field.mono }">{{ displayValue(field.value) }}</span>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="cleanupVisible" title="清理日志" width="460px">
      <div class="yx-hint">
        将删除设定天数之前的全部日志（消息、AI、搜索、推送、操作），操作不可撤销，请谨慎确认。
      </div>
      <el-form label-position="top" style="margin-top: 16px">
        <el-form-item label="保留最近天数">
          <el-input-number
            v-model="cleanupDays"
            :min="1"
            :max="3650"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>

      <div v-if="cleanupResult" class="cleanup-stats">
        <div v-for="(label, key) in cleanupLabels" :key="key" class="cleanup-stat">
          <span class="muted">{{ label }}</span>
          <strong>{{ cleanupResult[key] || 0 }}</strong>
        </div>
      </div>

      <template #footer>
        <el-button @click="cleanupVisible = false">取消</el-button>
        <el-button type="danger" :loading="cleanupLoading" @click="doCleanup">
          开始清理
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Download, RefreshLeft, Search } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import { cleanupLogs, downloadBlob, exportLogs, listLogs } from '@/api/log'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime, logStatusType, truncate } from '@/utils/format'

const auth = useAuthStore()

const tabs = [
  { name: 'message', label: '消息日志' },
  { name: 'ai', label: 'AI 日志' },
  { name: 'search', label: '搜索日志' },
  { name: 'push', label: '推送日志' },
  { name: 'operation', label: '操作日志' },
]

const activeType = ref('message')
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const dateRange = ref(null)
const loading = ref(false)
const exporting = ref(false)
const defaultTime = [new Date(2000, 1, 1, 0, 0, 0), new Date(2000, 1, 1, 23, 59, 59)]

const detailVisible = ref(false)
const detailRow = ref(null)

const cleanupVisible = ref(false)
const cleanupDays = ref(30)
const cleanupLoading = ref(false)
const cleanupResult = ref(null)
const cleanupLabels = {
  message: '消息日志',
  ai: 'AI 日志',
  search: '搜索日志',
  push: '推送日志',
  operation: '操作日志',
}

function buildParams() {
  return {
    page: page.value,
    page_size: pageSize.value,
    keyword: keyword.value.trim() || undefined,
    start: dateRange.value?.[0] || undefined,
    end: dateRange.value?.[1] || undefined,
  }
}

async function load() {
  loading.value = true
  try {
    const data = await listLogs(activeType.value, buildParams())
    rows.value = data.items || []
    total.value = data.total || 0
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

function reset() {
  keyword.value = ''
  dateRange.value = null
  page.value = 1
  load()
}

function handleTabChange() {
  page.value = 1
  rows.value = []
  total.value = 0
  load()
}

function handleSizeChange(size) {
  pageSize.value = size
  page.value = 1
  load()
}

function handleCurrentChange(value) {
  page.value = value
  load()
}

async function exportCsv() {
  exporting.value = true
  try {
    const data = await exportLogs(activeType.value, {
      keyword: keyword.value.trim() || undefined,
      start: dateRange.value?.[0] || undefined,
      end: dateRange.value?.[1] || undefined,
    })
    downloadBlob(data, `${activeType.value}_logs.csv`)
    ElMessage.success('日志导出已开始')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    exporting.value = false
  }
}

function openDetail(row) {
  detailRow.value = row
  detailVisible.value = true
}

function displayValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function sceneLabel(scene) {
  return { private: '私聊', group: '群聊' }[scene] || scene || '-'
}

function statusLabel(status) {
  return { ok: '正常', blocked: '已拦截', failed: '失败' }[status] || status || '-'
}

function levelType(level) {
  return { info: 'info', warning: 'warning', error: 'danger' }[level] || 'info'
}

function levelLabel(level) {
  return { info: '信息', warning: '警告', error: '错误' }[level] || level || '-'
}

const detailFields = computed(() => {
  const row = detailRow.value
  if (!row) return []
  const base = [
    { label: '日志 ID', value: row.id, mono: true },
    { label: '时间', value: formatDateTime(row.created_at) },
  ]

  if (activeType.value === 'message') {
    return [
      ...base,
      { label: '平台', value: row.platform },
      { label: '方向', value: row.direction === 'in' ? '接收' : '发送' },
      { label: '场景', value: sceneLabel(row.scene) },
      { label: '群号', value: row.group_id, mono: true },
      { label: '用户 ID', value: row.user_id, mono: true },
      { label: '昵称', value: row.nickname },
      { label: '状态', value: statusLabel(row.status) },
      { label: '错误', value: row.error, pre: true },
      { label: '完整内容', value: row.content, pre: true },
    ]
  }

  if (activeType.value === 'ai') {
    return [
      ...base,
      { label: '模型', value: row.model_name || row.model_id },
      { label: '输入 Tokens', value: row.prompt_tokens ?? 0, mono: true },
      { label: '输出 Tokens', value: row.completion_tokens ?? 0, mono: true },
      { label: '总 Tokens', value: (row.prompt_tokens ?? 0) + (row.completion_tokens ?? 0), mono: true },
      { label: '场景', value: sceneLabel(row.scene) },
      { label: '用户 ID', value: row.user_id, mono: true },
      { label: '延迟', value: `${row.latency_ms ?? 0} ms` },
      { label: '状态', value: row.success ? '成功' : '失败' },
      { label: '错误', value: row.error, pre: true },
      { label: '输入', value: row.prompt_preview, pre: true },
      { label: '输出', value: row.response_preview, pre: true },
    ]
  }

  if (activeType.value === 'search') {
    return [
      ...base,
      { label: '查询', value: row.query },
      { label: '触发方式', value: row.trigger_mode === 'auto' ? '自动' : '手动' },
      { label: '服务商', value: row.provider },
      { label: '结果数', value: row.result_count },
      { label: '耗时', value: `${row.latency_ms ?? 0} ms` },
      { label: '成功', value: row.success ? '成功' : '失败' },
      { label: '错误', value: row.error, pre: true },
      { label: '摘要', value: row.summary_preview, pre: true },
    ]
  }

  if (activeType.value === 'push') {
    return [
      ...base,
      { label: '任务 ID', value: row.task_id, mono: true },
      { label: '目标', value: `${row.target_type === 'group' ? '群聊' : '私聊'} ${row.target_id || ''}` },
      { label: '成功', value: row.success ? '成功' : '失败' },
      { label: '错误', value: row.error, pre: true },
    ]
  }

  return [
    ...base,
    { label: '级别', value: levelLabel(row.level) },
    { label: '模块', value: row.module, mono: true },
    { label: '动作', value: row.action },
    { label: '用户 ID', value: row.user_id, mono: true },
    { label: 'IP', value: row.ip, mono: true },
    { label: '详情', value: row.detail, pre: true },
  ]
})

function openCleanup() {
  cleanupResult.value = null
  cleanupVisible.value = true
}

async function doCleanup() {
  if (!cleanupDays.value) {
    ElMessage.warning('请输入保留天数')
    return
  }
  cleanupLoading.value = true
  try {
    const data = await cleanupLogs(cleanupDays.value)
    cleanupResult.value = data.deleted || {}
    ElMessage.success(data.message || '清理完成')
    page.value = 1
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    cleanupLoading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.log-tabs {
  margin-top: -6px;
  margin-bottom: 4px;
}

.log-keyword { width: 250px; }
.log-date-range { width: 380px; max-width: 100%; }
.log-filters { gap: 10px; }
.detail-value { overflow-wrap: anywhere; }

.cell-link {
  display: inline-block;
  max-width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  font: inherit;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  white-space: nowrap;
  color: var(--yx-text-2);
  cursor: pointer;
  transition: color 0.15s ease;
}

.cell-link.yx-danger-text {
  color: var(--el-color-danger);
}

.cell-link:hover,
.cell-link:focus-visible {
  color: var(--yx-accent);
}

.cell-link:focus-visible {
  outline: 2px solid var(--yx-accent);
  outline-offset: -2px;
  border-radius: 3px;
}

.target-id {
  margin-left: 6px;
  color: var(--yx-text-2);
}

.detail-pre {
  margin: 0;
  max-height: 360px;
  overflow: auto;
  font-family: var(--el-font-family);
  font-size: 12.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.cleanup-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.cleanup-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--yx-bg);
  font-size: 12px;
}

.cleanup-stat strong {
  font-size: 17px;
  color: var(--yx-text);
}

@media (max-width: 720px) {
  .yx-toolbar .el-input,
  .yx-toolbar .el-date-editor {
    width: 100% !important;
  }
  .log-filters .yx-toolbar-spacer { display: none; }
  .log-date-range { flex-basis: 100%; min-width: 0; }
  .log-date-range :deep(.el-range-input) { min-width: 0; font-size: 12px; }
  .log-date-range :deep(.el-range-separator) { flex: none; padding: 0 4px; }
}
</style>
