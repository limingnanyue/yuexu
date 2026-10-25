<template>
  <div class="yx-page">
    <PageHeader title="群组规则" description="单群能力开关、欢迎语、屏蔽词与防刷屏；无规则的群默认可聊，建规则后按规则控制">
      <el-button type="primary" :icon="Plus" @click="openCreate">新增群规则</el-button>
    </PageHeader>

    <div class="yx-card">
      <div class="yx-toolbar">
        <el-select
          v-model="filters.bot_id"
          placeholder="全部机器人账号"
          clearable
          class="rule-filter"
          aria-label="按机器人账号筛选群规则"
          @change="handleSearch"
        >
          <el-option
            v-for="account in accounts"
            :key="account.id"
            :label="accountLabel(account)"
            :value="account.id"
          />
        </el-select>
        <el-input
          v-model="filters.keyword"
          placeholder="搜索群号 / 群名"
          clearable
          class="rule-filter"
          aria-label="搜索群号或群名"
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
        <div class="yx-toolbar-spacer"></div>
        <span class="muted small">共 {{ total }} 条规则</span>
      </div>

      <el-table v-loading="loading" :data="rows" border stripe>
        <el-table-column label="群号" width="140">
          <template #default="{ row }">
            <span class="mono">{{ row.group_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="群名" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.group_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="机器人 ID" width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.bot_id" class="mono">{{ row.bot_id }}</span>
            <el-tag v-else size="small" type="info" effect="plain">全局规则</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="能力开关" min-width="300">
          <template #default="{ row }">
            <div class="capability-tags">
              <el-tag
                v-for="capability in capabilityFields"
                :key="capability.key"
                size="small"
                effect="plain"
                :type="!capability.disabled && row[capability.key] ? 'success' : 'info'"
              >
                {{ capability.label }}{{ !capability.disabled && row[capability.key] ? '开' : '关' }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="欢迎语" width="90" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              effect="plain"
              :type="row.welcome_enabled ? 'success' : 'info'"
            >
              {{ row.welcome_enabled ? '开' : '关' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="屏蔽词" width="80" align="center">
          <template #default="{ row }">
            {{ (row.block_words || []).length }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
            <el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button
              link
              type="danger"
              :icon="Delete"
              :loading="deletingId === row.id"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无群规则，点击右上角新增" :image-size="80" />
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

    <div class="yx-card">
      <div class="yx-card-title">
        <h3>群成员管理</h3>
        <span class="muted small">需机器人账号处于在线状态</span>
      </div>
      <el-form label-position="top" class="member-form" @submit.prevent>
        <el-form-item label="机器人账号">
          <el-select
            v-model="memberForm.bot_id"
            placeholder="选择账号"
            filterable
          >
            <el-option
              v-for="account in accounts"
              :key="account.id"
              :label="accountLabel(account)"
              :value="account.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="群号">
          <el-input v-model="memberForm.group_id" placeholder="群号" />
        </el-form-item>
        <el-form-item label="用户 ID">
          <el-input
            v-model="memberForm.user_id"
            placeholder="用户 ID"
          />
        </el-form-item>
        <el-form-item label="禁言时长">
          <el-input-number
            v-model="memberForm.seconds"
            :min="1"
            :max="86400"
            controls-position="right"
          />
        </el-form-item>
        <el-form-item class="member-actions">
          <el-button
            type="warning"
            plain
            :loading="memberAction === 'mute'"
            @click="handleMute"
          >
            禁言
          </el-button>
          <el-button
            type="danger"
            plain
            :loading="memberAction === 'kick'"
            @click="handleKick"
          >
            踢出
          </el-button>
        </el-form-item>
      </el-form>
      <div class="yx-hint">
        禁言时长单位为秒，默认 60 秒；踢出操作不可撤销，请谨慎执行。
      </div>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑群规则' : '新增群规则'"
      width="680px"
      :close-on-click-modal="false"
    >
      <el-tabs v-model="activeTab">
        <el-tab-pane label="基础与能力" name="basic">
          <div class="yx-hint rule-hint">
            机器人账号留空时，该规则作为全局规则，对未单独配置的群生效。主动推送开启后，定时推送与活力 Agent 才会在该群主动发言（默认关闭，保持被动回应）。
          </div>
          <el-form label-position="top">
            <div class="form-grid">
              <el-form-item label="机器人账号">
                <el-select
                  v-model="form.bot_id"
                  placeholder="留空表示全局规则"
                  clearable
                >
                  <el-option
                    v-for="account in accounts"
                    :key="account.id"
                    :label="accountLabel(account)"
                    :value="account.id"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="群号" required>
                <el-input v-model="form.group_id" placeholder="例如 123456789" clearable />
              </el-form-item>
              <el-form-item label="群名">
                <el-input v-model="form.group_name" placeholder="可选，便于识别" clearable />
              </el-form-item>
            </div>
            <el-divider content-position="left">能力开关</el-divider>
            <div class="switch-grid">
              <div v-for="capability in capabilityFields" :key="capability.key" class="switch-item">
                <span>{{ capability.label }}</span>
                <el-switch v-model="form[capability.key]" :disabled="capability.disabled" />
              </div>
            </div>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="欢迎与退群" name="welcome">
          <div class="yx-hint rule-hint">开启后，机器人会在新成员入群时发送欢迎语，成员退群时发送提示（需机器人为群管理员才能收到部分通知）。</div>
          <el-form label-position="top">
            <el-form-item label="入群欢迎">
              <el-switch
                v-model="form.welcome_enabled"
                active-text="开启"
                inactive-text="关闭"
              />
            </el-form-item>
            <el-form-item label="欢迎语">
              <el-input
                v-model="form.welcome_text"
                type="textarea"
                :rows="3"
                placeholder="支持占位符 {name} / {group}，{name} 会 @ 新成员"
              />
            </el-form-item>
            <el-form-item label="退群提示">
              <el-input
                v-model="form.leave_notice"
                type="textarea"
                :rows="3"
                placeholder="支持占位符 {name} / {group}，留空则不提示"
              />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="过滤" name="filter">
          <el-form label-position="top">
            <el-form-item label="屏蔽词">
              <el-input
                v-model="form.block_words"
                type="textarea"
                :rows="6"
                placeholder="一行一个屏蔽词，命中后消息会被拦截"
              />
            </el-form-item>
            <el-form-item label="黑名单用户">
              <el-input
                v-model="form.blacklist"
                type="textarea"
                :rows="6"
                placeholder="一行一个用户 ID，命中后忽略其消息"
              />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="防刷屏与覆盖" name="advanced">
          <el-form label-position="top">
            <el-form-item label="防刷屏">
              <el-switch
                v-model="form.anti_flood_enabled"
                active-text="开启"
                inactive-text="关闭"
              />
            </el-form-item>
            <div class="form-grid">
              <el-form-item label="统计窗口（秒）">
                <el-input-number
                  v-model="form.flood_window_seconds"
                  :min="5"
                  :max="3600"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="窗口内最大消息数">
                <el-input-number
                  v-model="form.flood_max_messages"
                  :min="2"
                  :max="200"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="触发禁言时长（秒）">
                <el-input-number
                  v-model="form.flood_mute_seconds"
                  :min="0"
                  :max="86400"
                  controls-position="right"
                />
              </el-form-item>
            </div>
            <el-divider content-position="left">就近覆盖</el-divider>
            <div class="form-grid">
              <el-form-item label="人设 ID">
                <el-input
                  v-model="form.character_id"
                  placeholder="留空则使用账号 / 全局人设"
                  clearable
                />
              </el-form-item>
              <el-form-item label="模型 ID">
                <el-input
                  v-model="form.model_id"
                  placeholder="留空则使用账号 / 全局模型"
                  clearable
                />
              </el-form-item>
            </div>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Refresh, Search } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import { listAccounts } from '@/api/account'
import {
  createRule,
  deleteRule,
  kickMember,
  listRules,
  muteMember,
  updateRule,
} from '@/api/group'

const capabilityFields = [
  { key: 'enabled_ai', label: 'AI' },
  { key: 'enabled_emoji', label: '表情' },
  { key: 'enabled_voice', label: '语音' },
  { key: 'enabled_search', label: '搜索' },
  { key: 'enabled_push', label: '主动推送' },
  { key: 'enabled_memory', label: '记忆' },
]

function emptyForm() {
  return {
    bot_id: '',
    group_id: '',
    group_name: '',
    enabled_ai: true,
    enabled_emoji: true,
    enabled_voice: true,
    enabled_search: true,
    enabled_push: false,
    enabled_memory: true,
    welcome_enabled: false,
    welcome_text: '',
    leave_notice: '',
    block_words: '',
    blacklist: '',
    anti_flood_enabled: true,
    flood_window_seconds: 60,
    flood_max_messages: 8,
    flood_mute_seconds: 60,
    character_id: '',
    model_id: '',
  }
}

function accountLabel(account) {
  const suffix = account.account_no ? ` · ${account.account_no}` : ''
  return `${account.name || account.id}${suffix}`
}

function splitLines(text) {
  return String(text || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function toNumber(value, fallback) {
  if (value === null || value === undefined || value === '') return fallback
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

const accounts = ref([])
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const deletingId = ref('')
const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref('')
const activeTab = ref('basic')
const form = reactive(emptyForm())

const memberForm = reactive({
  bot_id: '',
  group_id: '',
  user_id: '',
  seconds: 60,
})
const memberAction = ref('')

const filters = reactive({
  bot_id: '',
  keyword: '',
})

async function loadAccounts() {
  try {
    accounts.value = (await listAccounts()) || []
  } catch {
    accounts.value = []
  }
  if (!memberForm.bot_id && accounts.value.length) {
    memberForm.bot_id = accounts.value[0].id
  }
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize }
    if (filters.bot_id) params.bot_id = filters.bot_id
    const keyword = filters.keyword.trim()
    if (keyword) params.keyword = keyword
    const data = await listRules(params)
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

function resetFilters() {
  filters.bot_id = ''
  filters.keyword = ''
  handleSearch()
}

function openCreate() {
  editingId.value = ''
  activeTab.value = 'basic'
  Object.assign(form, emptyForm(), { bot_id: filters.bot_id || '' })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  activeTab.value = 'basic'
  Object.assign(form, emptyForm(), {
    bot_id: row.bot_id || '',
    group_id: row.group_id || '',
    group_name: row.group_name || '',
    enabled_ai: row.enabled_ai !== false,
    enabled_emoji: row.enabled_emoji !== false,
    enabled_voice: row.enabled_voice !== false,
    enabled_search: row.enabled_search !== false,
    enabled_push: row.enabled_push === true,
    enabled_memory: row.enabled_memory !== false,
    welcome_enabled: row.welcome_enabled === true,
    welcome_text: row.welcome_text || '',
    leave_notice: row.leave_notice || '',
    block_words: (row.block_words || []).join('\n'),
    blacklist: (row.blacklist || []).join('\n'),
    anti_flood_enabled: row.anti_flood_enabled !== false,
    flood_window_seconds: toNumber(row.flood_window_seconds, 60),
    flood_max_messages: toNumber(row.flood_max_messages, 8),
    flood_mute_seconds: toNumber(row.flood_mute_seconds, 60),
    character_id: row.character_id || '',
    model_id: row.model_id || '',
  })
  dialogVisible.value = true
}

async function saveRule() {
  const groupId = form.group_id.trim()
  if (!groupId) {
    activeTab.value = 'basic'
    ElMessage.warning('请填写群号')
    return
  }

  const payload = {
    bot_id: form.bot_id || null,
    group_id: groupId,
    group_name: form.group_name.trim(),
    enabled_ai: form.enabled_ai,
    enabled_emoji: form.enabled_emoji,
    enabled_voice: form.enabled_voice,
    enabled_search: form.enabled_search,
    enabled_push: form.enabled_push,
    enabled_memory: form.enabled_memory,
    welcome_enabled: form.welcome_enabled,
    welcome_text: form.welcome_text,
    leave_notice: form.leave_notice,
    block_words: splitLines(form.block_words),
    blacklist: splitLines(form.blacklist),
    anti_flood_enabled: form.anti_flood_enabled,
    flood_window_seconds: Math.round(toNumber(form.flood_window_seconds, 60)),
    flood_max_messages: Math.round(toNumber(form.flood_max_messages, 8)),
    flood_mute_seconds: Math.round(toNumber(form.flood_mute_seconds, 60)),
    character_id: form.character_id.trim(),
    model_id: form.model_id.trim(),
  }

  saving.value = true
  try {
    if (editingId.value) {
      await updateRule(editingId.value, payload)
      ElMessage.success('群规则已更新')
    } else {
      await createRule(payload)
      ElMessage.success('群规则已创建')
    }
    dialogVisible.value = false
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    saving.value = false
  }
}

async function handleDelete(row) {
  const name = row.group_name ? `（${row.group_name}）` : ''
  try {
    await ElMessageBox.confirm(
      `确定删除群 ${row.group_id}${name} 的规则吗？删除后不可恢复。`,
      '删除群规则',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  deletingId.value = row.id
  try {
    await deleteRule(row.id)
    ElMessage.success('已删除')
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    deletingId.value = ''
  }
}

function validateMember() {
  if (!memberForm.bot_id) {
    ElMessage.warning('请选择机器人账号')
    return false
  }
  if (!memberForm.group_id.trim()) {
    ElMessage.warning('请输入群号')
    return false
  }
  if (!memberForm.user_id.trim()) {
    ElMessage.warning('请输入用户 ID')
    return false
  }
  return true
}

async function handleMute() {
  if (!validateMember()) return
  memberAction.value = 'mute'
  try {
    const data = await muteMember({
      bot_id: memberForm.bot_id,
      group_id: memberForm.group_id.trim(),
      user_id: memberForm.user_id.trim(),
      seconds: Math.round(toNumber(memberForm.seconds, 60)),
    })
    if (data?.success) {
      ElMessage.success('禁言成功')
    } else {
      ElMessage.error(data?.error || '禁言失败')
    }
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    memberAction.value = ''
  }
}

async function handleKick() {
  if (!validateMember()) return
  memberAction.value = 'kick'
  try {
    const data = await kickMember({
      bot_id: memberForm.bot_id,
      group_id: memberForm.group_id.trim(),
      user_id: memberForm.user_id.trim(),
    })
    if (data?.success) {
      ElMessage.success('已踢出群成员')
    } else {
      ElMessage.error(data?.error || '踢出失败')
    }
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    memberAction.value = ''
  }
}

onMounted(() => {
  loadAccounts()
  load()
})
</script>

<style scoped>
.rule-filter { width: 240px; max-width: 100%; }
.rule-hint { margin-bottom: 20px; }
.table-actions { display: flex; align-items: center; gap: 16px; }
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0 16px;
}

.form-grid :deep(.el-select), .form-grid :deep(.el-input-number) { width: 100%; }

.switch-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0 24px;
  margin-bottom: 16px;
}

.switch-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 52px;
  padding: 10px 0;
  border-bottom: 1px solid var(--yx-line);
  font-size: 13px;
  color: var(--yx-text-2);
}

.capability-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.member-form {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0 16px;
  margin-bottom: 0;
}

.member-form :deep(.el-form-item) {
  min-width: 0;
  margin-right: 0;
  margin-bottom: 16px;
}

.member-form :deep(.el-select), .member-form :deep(.el-input-number) { width: 100%; }
.member-actions { grid-column: 1 / -1; }
.member-actions :deep(.el-form-item__content) { gap: 8px; }

@media (max-width: 1000px) {
  .member-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 760px) {
  .rule-filter { flex: 1 1 100%; width: 100%; }
  .member-form { gap: 0 12px; }
  .member-actions :deep(.el-button) { flex: 1; }
}

@media (max-width: 420px) {
  .form-grid, .member-form { grid-template-columns: 1fr; }
}
</style>
