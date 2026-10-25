<template>
  <div class="yx-page">
    <PageHeader title="私聊惦记" description="在对话空档偶然想起，尊重每个人的回复节奏。">
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </PageHeader>

    <div class="yx-hint">
      仅私聊支持主动消息，群聊仅被动回应。每人每天最多 2 条、每周最多 3 条，多数日子不发送。
      用户说「不要主动发消息」后将永久关闭，只有用户在私聊明确重新开启才会恢复。
    </div>

    <div class="yx-card push-panel">
      <el-tabs v-model="activeTab" @tab-change="load">
        <el-tab-pane label="私聊用户" name="users">
          <form class="yx-toolbar push-toolbar" @submit.prevent="searchUsers">
            <label class="query-field">
              <span>用户 / 账号</span>
              <el-input v-model="keyword" placeholder="搜索用户 ID 或账号" clearable :disabled="usersLoading" />
            </label>
            <el-button type="primary" :icon="Search" native-type="submit" :disabled="usersLoading">查询</el-button>
            <div class="yx-toolbar-spacer"></div>
            <span class="muted small">共 {{ userTotal }} 位私聊用户</span>
          </form>
          <el-alert v-if="userError" :title="userError" type="warning" :closable="false" show-icon />
          <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" show-icon />

          <el-table v-loading="usersLoading" :data="users" :row-key="userKey">
            <el-table-column label="私聊用户" min-width="170">
              <template #default="{ row }">
                <div class="mono">{{ row.user_id }}</div>
                <div class="muted small">{{ row.account_name || row.bot_id }}</div>
              </template>
            </el-table-column>
            <el-table-column label="主动消息状态" min-width="200">
              <template #default="{ row }">
                <el-tag :type="userStatus(row).type" size="small" effect="plain">{{ userStatus(row).label }}</el-tag>
                <div v-if="!row.user_push_switch" class="muted small cell-note">需用户在私聊重新开启</div>
                <div v-else-if="row.sleep_until" class="muted small cell-note">休眠至 {{ formatDateTime(row.sleep_until) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="频次 / 忽略" min-width="150">
              <template #default="{ row }">
                <div>今日 {{ row.day_push_count }} / 2 · 本周 {{ row.week_push_count }} / 3</div>
                <div class="muted small">连续忽略 {{ row.ignore_count }} 次</div>
              </template>
            </el-table-column>
            <el-table-column label="最近收到消息" min-width="165">
              <template #default="{ row }">{{ row.last_message_at ? formatDateTime(row.last_message_at) : '—' }}</template>
            </el-table-column>
            <el-table-column label="下次聊天机会" min-width="170">
              <template #default="{ row }">
                <span v-if="row.next_idle_at && row.user_push_switch">{{ formatDateTime(row.next_idle_at) }}</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="190">
              <template #default="{ row }">
                <el-button link type="primary" :disabled="recordsLoading" @click="viewRecords(row)">查看记录</el-button>
                <el-button
                  v-if="row.user_push_switch"
                  link
                  type="danger"
                  :loading="stopBusy === userKey(row)"
                  :disabled="!!stopBusy"
                  @click="stopPush(row)"
                >停止主动消息</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty :description="userError ? '暂时无法读取私聊用户，请刷新重试' : '暂无匹配的私聊用户，用户发来私聊后会出现在这里'" /></template>
          </el-table>
          <el-pagination
            v-if="userTotal > pageSize"
            v-model:current-page="userPage"
            :page-size="pageSize"
            :total="userTotal"
            :disabled="usersLoading"
            background
            layout="total, prev, pager, next"
            @current-change="loadUsers"
          />
        </el-tab-pane>

        <el-tab-pane label="推送记录" name="records">
          <form class="yx-toolbar push-toolbar" @submit.prevent="searchRecords">
            <label class="query-field">
              <span>机器人账号 ID</span>
              <el-input v-model="recordQuery.bot_id" placeholder="全部账号" clearable :disabled="recordsLoading" />
            </label>
            <label class="query-field">
              <span>用户 ID</span>
              <el-input v-model="recordQuery.user_id" placeholder="全部私聊用户" clearable :disabled="recordsLoading" />
            </label>
            <el-button type="primary" :icon="Search" native-type="submit" :disabled="recordsLoading">查询</el-button>
            <el-button :disabled="recordsLoading" @click="resetRecords">重置</el-button>
            <div class="yx-toolbar-spacer"></div>
            <span class="muted small">共 {{ recordTotal }} 条记录</span>
          </form>
          <el-alert v-if="recordError" :title="recordError" type="warning" :closable="false" show-icon />

          <el-table v-loading="recordsLoading" :data="records" row-key="id">
            <el-table-column label="用户 / 账号" min-width="170">
              <template #default="{ row }">
                <div class="mono">{{ row.user_id }}</div>
                <div class="muted small mono">{{ row.bot_id }}</div>
              </template>
            </el-table-column>
            <el-table-column label="触发来源" min-width="110">
              <template #default="{ row }">{{ triggerLabels[row.trigger_type] || row.trigger_type }}</template>
            </el-table-column>
            <el-table-column label="推送内容" min-width="240">
              <template #default="{ row }">
                <div class="push-content">{{ row.push_content || '—' }}</div>
                <div v-if="row.error" class="yx-danger-text small cell-note">{{ row.error }}</div>
              </template>
            </el-table-column>
            <el-table-column label="发送时间" min-width="165">
              <template #default="{ row }">{{ formatDateTime(row.send_time) }}</template>
            </el-table-column>
            <el-table-column label="反馈状态" min-width="165">
              <template #default="{ row }">
                <el-tag :type="recordStatus(row).type" size="small" effect="plain">{{ recordStatus(row).label }}</el-tag>
                <div v-if="row.replied_at" class="muted small cell-note">回复于 {{ formatDateTime(row.replied_at) }}</div>
                <div v-else-if="row.read_at" class="muted small cell-note">已读于 {{ formatDateTime(row.read_at) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="留存状态" min-width="190">
              <template #default="{ row }">
                <div class="small">忽略 {{ row.ignore_count }} 次 · 本周 {{ row.week_push_count }} 条</div>
                <div v-if="row.sleep_until" class="muted small">休眠至 {{ formatDateTime(row.sleep_until) }}</div>
              </template>
            </el-table-column>
            <template #empty><el-empty :description="recordError ? '暂时无法读取推送记录，请刷新重试' : '暂无匹配的推送记录'" /></template>
          </el-table>
          <el-pagination
            v-if="recordTotal > pageSize"
            v-model:current-page="recordPage"
            :page-size="pageSize"
            :total="recordTotal"
            :disabled="recordsLoading"
            background
            layout="total, prev, pager, next"
            @current-change="loadRecords"
          />
        </el-tab-pane>
      </el-tabs>
    </div>

    <section class="yx-card push-rules-panel" aria-labelledby="push-rules-title">
      <div class="yx-card-title"><h3 id="push-rules-title">惦记规则</h3><span class="muted small">自动执行，随时尊重用户选择</span></div>
      <ul class="push-rules">
        <li>按记忆关联 → 离线空闲 → 冷场兜底的顺序尝试，只在对话空档触发，不发送固定早安晚安。</li>
        <li>空闲 6–24 小时内随机安排一次机会，25% 概率尝试；冷场至少 3 天且近 7 天未推送，才有 10% 概率兜底，触发后冷却 7 天。</li>
        <li>结合当前人设、最近私聊与记忆，每条最多 40 字、1 个表情，可以自然提问。首条发出后若仍未回复，在 10–30 分钟内最多轻轻接话一次；接话也计入日周上限。</li>
        <li>用户一旦回复，立即取消待发接话，结束本轮主动消息并清零忽略计数。生成或发送失败不重试，超时接话不补发。</li>
        <li>未读保持待反馈；发送 12 小时后已读未回复才计为忽略。连续忽略 2 次，休眠 7 天，期满清零。</li>
      </ul>
      <p class="muted small feedback-note">已读状态依赖平台回执；没有已读回执时保持待反馈，不会把未读当作忽略。</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { listPushRecords, listPushUsers, stopUserPush } from '@/api/push'
import { formatDateTime } from '@/utils/format'

const activeTab = ref('users')
const pageSize = 20
const keyword = ref('')
const users = ref([])
const userPage = ref(1)
const userTotal = ref(0)
const usersLoading = ref(false)
const userError = ref('')
const actionError = ref('')
const stopBusy = ref('')
const records = ref([])
const recordPage = ref(1)
const recordTotal = ref(0)
const recordsLoading = ref(false)
const recordError = ref('')
const recordQuery = reactive({ bot_id: '', user_id: '' })
const loading = computed(() => activeTab.value === 'users' ? usersLoading.value : recordsLoading.value)
const triggerLabels = { memory: '记忆关联', idle: '离线空闲', followup: '自然接话', fallback: '冷场兜底' }

function userKey(row) {
  return JSON.stringify([row.bot_id, row.user_id])
}

function userStatus(row) {
  if (!row.user_push_switch) return { label: '已关闭', type: 'info' }
  if (row.sleep_until && new Date(row.sleep_until) > new Date()) return { label: '休眠中', type: 'warning' }
  return { label: '允许偶尔惦记', type: 'success' }
}

function recordStatus(row) {
  if (row.sent === false) return { label: '发送失败', type: 'danger' }
  if (row.status === 'replied') return { label: '已回复', type: 'success' }
  if (row.status === 'ignored') return { label: '已读未回复', type: 'warning' }
  if (row.status === 'pending') return { label: row.read_at ? '已读待回复' : '未读待反馈', type: 'info' }
  return { label: '未知状态', type: 'info' }
}

async function loadUsers() {
  if (usersLoading.value) return
  usersLoading.value = true
  try {
    const data = await listPushUsers({ page: userPage.value, page_size: pageSize, keyword: keyword.value.trim() })
    users.value = data.items || []
    userTotal.value = data.total ?? 0
    userError.value = ''
  } catch {
    userError.value = '读取私聊用户失败，保留上次数据，请刷新重试。'
  } finally {
    usersLoading.value = false
  }
}

async function loadRecords() {
  if (recordsLoading.value) return
  recordsLoading.value = true
  try {
    const data = await listPushRecords({
      page: recordPage.value,
      page_size: pageSize,
      bot_id: recordQuery.bot_id.trim() || undefined,
      user_id: recordQuery.user_id.trim() || undefined,
    })
    records.value = data.items || []
    recordTotal.value = data.total ?? 0
    recordError.value = ''
  } catch {
    recordError.value = '读取推送记录失败，保留上次数据，请刷新重试。'
  } finally {
    recordsLoading.value = false
  }
}

function load() {
  return activeTab.value === 'users' ? loadUsers() : loadRecords()
}

function searchUsers() {
  userPage.value = 1
  return loadUsers()
}

function searchRecords() {
  recordPage.value = 1
  return loadRecords()
}

function resetRecords() {
  Object.assign(recordQuery, { bot_id: '', user_id: '' })
  return searchRecords()
}

function viewRecords(row) {
  Object.assign(recordQuery, { bot_id: row.bot_id, user_id: row.user_id })
  activeTab.value = 'records'
  return searchRecords()
}

async function stopPush(row) {
  if (!row.user_push_switch || stopBusy.value) return
  stopBusy.value = userKey(row)
  actionError.value = ''
  try {
    await stopUserPush(row.bot_id, row.user_id)
    row.user_push_switch = false
    ElMessage.success('已停止主动消息，需用户在私聊重新开启')
  } catch {
    actionError.value = '停止主动消息失败，请检查连接后重试。'
  } finally {
    stopBusy.value = ''
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.push-toolbar { align-items: flex-end; padding: 8px 0 20px; border-bottom: 1px solid var(--yx-line); }
.query-field { display: flex; flex-direction: column; gap: 7px; width: 230px; max-width: 100%; color: var(--yx-muted); font-size: 12px; }
.push-panel :deep(.el-tabs__header) { margin-bottom: 16px; }
.push-toolbar > .small { padding-bottom: 8px; font-variant-numeric: tabular-nums; }
.push-panel :deep(.el-alert) { margin-bottom: 16px; }
.cell-note { margin-top: 5px; line-height: 1.6; }
.push-content { color: var(--yx-text); overflow-wrap: anywhere; line-height: 1.8; }
.push-rules { max-width: 90ch; margin: 0; padding-left: 20px; color: var(--yx-text-2); font-size: 13px; line-height: 1.9; }
.push-rules li { padding-left: 4px; }
.push-rules li::marker { color: var(--yx-muted); }
.push-rules li + li { margin-top: 12px; }
.feedback-note { margin: 20px 0 0; padding-top: 16px; border-top: 1px solid var(--yx-line); line-height: 1.8; }
@media (max-width: 620px) {
  .query-field { width: 100%; }
  .push-toolbar .yx-toolbar-spacer { display: none; }
  .push-toolbar > .muted { width: 100%; }
  .push-rules-panel .yx-card-title { align-items: flex-start; flex-direction: column; }
}
</style>
