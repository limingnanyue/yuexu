<template>
  <div class="yx-page">
    <PageHeader title="上下文会话" description="会话列表、历史快照、冻结与清理">
      <el-button :icon="Refresh" :loading="cleaning" @click="handleCleanup">
        清理无效会话
      </el-button>
      <el-button
        type="danger"
        plain
        :icon="Delete"
        :loading="clearingAll"
        @click="handleClearAll"
      >
        清空全部
      </el-button>
    </PageHeader>

    <div class="yx-hint">
      会话 Key 规则：私聊
      <code class="mono">ctx:private:{bot}:{user}</code>，群聊
      <code class="mono">ctx:group:{bot}:{group}:{user}</code>。原文保存于数据库，缓存过期或重启后自动恢复；
      冻结会话保留历史但不再写入新轮次。
    </div>

    <div class="yx-card">
      <div class="yx-toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索会话 Key / 用户 / 群号"
          clearable
          class="session-search"
          aria-label="搜索会话 Key、用户或群号"
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-button type="primary" :icon="Search" @click="handleSearch">搜索</el-button>
        <div class="yx-toolbar-spacer"></div>
        <span class="muted small">共 {{ total }} 个会话</span>
      </div>

      <el-table v-loading="loading" :data="rows" border stripe>
        <el-table-column label="会话 Key" min-width="300">
          <template #default="{ row }">
            <div class="key-cell">
              <span class="mono key-text" :title="row.session_key">{{ row.session_key }}</span>
              <el-button
                link
                type="primary"
                :icon="CopyDocument"
                title="复制会话 Key"
                aria-label="复制会话 Key"
                @click="copyKey(row.session_key)"
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="场景" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="sceneType(row.scene)">
              {{ sceneLabel(row.scene) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="群号" width="130">
          <template #default="{ row }">
            <span class="mono">{{ row.group_id || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="用户" width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono">{{ row.user_id || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="窗口消息" width="90" align="center">
          <template #default="{ row }">
            {{ (row.rounds || []).length }}
          </template>
        </el-table-column>
        <el-table-column label="冻结状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.frozen ? 'danger' : 'success'">
              {{ row.frozen ? '已冻结' : '正常' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近更新" width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="缓存 TTL" width="110" align="center">
          <template #default="{ row }">
            <span class="mono" :class="{ 'yx-danger-text': row.ttl === 0 }">
              {{ ttlText(row.ttl) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-button
              link
              :type="row.frozen ? 'success' : 'warning'"
              :loading="freezeKey === row.session_key"
              @click="toggleFreeze(row)"
            >
              {{ row.frozen ? '解冻' : '冻结' }}
            </el-button>
            <el-button
              link
              type="danger"
              :loading="clearKey === row.session_key"
              @click="handleClear(row)"
            >
              清空
            </el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无上下文会话" :image-size="80" />
        </template>
      </el-table>

      <el-pagination
        v-if="total > pageSize"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        background
        layout="total, prev, pager, next"
        @current-change="load"
      />
    </div>

    <el-drawer
      v-model="drawerVisible"
      title="会话详情"
      size="min(640px, 100vw)"
      @closed="handleDrawerClosed"
    >
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="detail">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="会话 Key" :span="2">
              <span class="mono">{{ detail.session_key }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="场景">
              <el-tag size="small" effect="plain" :type="sceneType(detail.scene)">
                {{ sceneLabel(detail.scene) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="冻结状态">
              <el-tag size="small" effect="plain" :type="detail.frozen ? 'danger' : 'success'">
                {{ detail.frozen ? '已冻结' : '正常' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="机器人 ID">
              <span class="mono">{{ detail.bot_id || '—' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="群号">
              <span class="mono">{{ detail.group_id || '—' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="用户 ID">
              <span class="mono">{{ detail.user_id || '—' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="窗口消息">
              {{ (detail.rounds || []).length }}
            </el-descriptions-item>
            <el-descriptions-item label="缓存 TTL">
              <span class="mono">{{ ttlText(detail.ttl) }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="最近更新">
              {{ formatTime(detail.updated_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="创建时间" :span="2">
              {{ formatTime(detail.created_at) }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="yx-divider"></div>

          <el-alert v-if="detail.summary" title="历史对话摘要" :description="detail.summary" type="info" :closable="false" />

          <div class="chat-title">
            <h4>聊天记录</h4>
            <span class="muted small">{{ (detail.archive || detail.rounds || []).length }} 条原始消息</span>
          </div>

          <div v-if="(detail.archive || detail.rounds || []).length" class="chat-list">
            <div
              v-for="(message, index) in detail.archive || detail.rounds || []"
              :key="`${message.ts || ''}-${index}`"
              class="chat-row"
              :class="message.role === 'user' ? 'from-user' : 'from-assistant'"
            >
              <div class="chat-block">
                <div class="chat-meta">
                  <span>{{ message.role === 'user' ? '用户' : '助手' }}</span>
                  <span class="muted small">{{ formatTime(message.ts) }}</span>
                </div>
                <div class="chat-bubble">{{ message.content }}</div>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无聊天记录" :image-size="70" />
        </template>
        <el-empty
          v-else-if="!detailLoading"
          description="会话不存在或已清空"
          :image-size="80"
        />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, Refresh, Search } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import {
  cleanupContexts,
  clearAllContexts,
  clearContext,
  contextDetail,
  freezeContext,
  listContexts,
  unfreezeContext,
} from '@/api/memory'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const keyword = ref('')
const loading = ref(false)
const cleaning = ref(false)
const clearingAll = ref(false)
const freezeKey = ref('')
const clearKey = ref('')
const drawerVisible = ref(false)
const detail = ref(null)
const detailLoading = ref(false)

function sceneLabel(scene) {
  return scene === 'group' ? '群聊' : '私聊'
}

function sceneType(scene) {
  return scene === 'group' ? 'warning' : 'info'
}

function formatTime(value) {
  return value ? String(value).replace('T', ' ') : '—'
}

function ttlText(ttl) {
  if (ttl === null || ttl === undefined) return '—'
  if (ttl === -1) return '已保存'
  if (ttl === 0) return '待重新缓存'
  if (ttl < 0) return '未缓存'
  return `${ttl} 秒`
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize }
    const kw = keyword.value.trim()
    if (kw) params.keyword = kw
    const data = await listContexts(params)
    rows.value = data.items || []
    total.value = data.total || 0
  } catch {
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  load()
}

async function handleCleanup() {
  cleaning.value = true
  try {
    const data = await cleanupContexts()
    ElMessage.success(`清理完成，移除 ${data.removed ?? 0} 个无效会话`)
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    cleaning.value = false
  }
}

async function handleClearAll() {
  try {
    await ElMessageBox.prompt(
      '此操作将删除全部上下文会话，且无法恢复。请输入「清空全部」确认。',
      '清空全部会话',
      {
        type: 'warning',
        confirmButtonText: '确认清空',
        cancelButtonText: '取消',
        inputPlaceholder: '请输入：清空全部',
        inputValidator: (value) => value === '清空全部' || '请输入「清空全部」以确认',
      },
    )
  } catch {
    return
  }

  clearingAll.value = true
  try {
    const data = await clearAllContexts()
    ElMessage.success(`已清空 ${data.removed ?? 0} 个会话`)
    page.value = 1
    drawerVisible.value = false
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    clearingAll.value = false
  }
}

async function toggleFreeze(row) {
  const key = row.session_key
  const nextFrozen = !row.frozen
  freezeKey.value = key
  try {
    if (nextFrozen) {
      await freezeContext({ session_key: key })
      ElMessage.success('会话已冻结，后续消息不再写入')
    } else {
      await unfreezeContext({ session_key: key })
      ElMessage.success('会话已解冻')
    }
    if (detail.value?.session_key === key) {
      detail.value.frozen = nextFrozen
    }
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    freezeKey.value = ''
  }
}

async function handleClear(row) {
  try {
    await ElMessageBox.confirm(
      `确定清空会话「${row.session_key}」的上下文吗？清空后不可恢复。`,
      '清空会话',
      {
        type: 'warning',
        confirmButtonText: '清空',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  clearKey.value = row.session_key
  try {
    const data = await clearContext({ session_key: row.session_key })
    ElMessage.success(data.message || '已清空')
    if (detail.value?.session_key === row.session_key) {
      drawerVisible.value = false
    }
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    clearKey.value = ''
  }
}

async function openDetail(row) {
  drawerVisible.value = true
  detail.value = null
  detailLoading.value = true
  try {
    detail.value = await contextDetail({ session_key: row.session_key })
  } catch {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function handleDrawerClosed() {
  detail.value = null
}

async function copyKey(key) {
  try {
    await navigator.clipboard.writeText(key)
    ElMessage.success('会话 Key 已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

onMounted(load)
</script>

<style scoped>
.session-search { width: 360px; max-width: 100%; }
.table-actions { display: flex; align-items: center; gap: 16px; }
.key-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.key-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-body {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-body :deep(.el-descriptions__table) { table-layout: fixed; }
.detail-body :deep(.el-descriptions__cell) { overflow-wrap: anywhere; }

.chat-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.chat-title h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.chat-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 8px 0 24px;
}

.chat-row {
  display: flex;
}

.chat-row.from-user {
  justify-content: flex-end;
}

.chat-block {
  max-width: 88%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.from-user .chat-block {
  align-items: flex-end;
}

.chat-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--yx-muted);
}

.chat-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  background: var(--yx-elevated);
  color: var(--yx-text);
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border-top-left-radius: 4px;
}

.from-user .chat-bubble {
  background: var(--yx-accent);
  color: #18202d;
  border-top-left-radius: 12px;
  border-top-right-radius: 4px;
}

@media (max-width: 760px) {
  .session-search { width: 100%; flex-basis: 100%; }
  .chat-block { max-width: 94%; }
  .chat-bubble { padding: 10px 12px; }
  .detail-body :deep(.el-descriptions__label) { width: 68px; }
}
</style>
