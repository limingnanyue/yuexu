<template>
  <div class="yx-page">
    <PageHeader title="系统设置" description="运行参数、数据备份、定时任务与后台账号">
      <el-button :icon="Refresh" :loading="refreshing" @click="loadAll">刷新</el-button>
    </PageHeader>

    <div class="yx-card" v-loading="infoLoading">
      <div class="yx-card-title">
        <h3>系统信息</h3>
        <el-tag size="small" effect="plain">{{ info?.env || '—' }}</el-tag>
      </div>
      <dl class="system-facts">
        <div><dt>应用</dt><dd>{{ info?.app || '—' }}</dd></div>
        <div><dt>版本</dt><dd class="mono">{{ info?.version || '—' }}</dd></div>
        <div><dt>运行环境</dt><dd>{{ info?.env || '—' }}</dd></div>
        <div><dt>Python</dt><dd class="mono">{{ info?.python || '—' }}</dd></div>
        <div class="fact-wide"><dt>操作系统</dt><dd>{{ info?.platform || '—' }}</dd></div>
        <div class="fact-wide"><dt>数据库</dt><dd class="mono">{{ info?.database || '—' }}</dd></div>
        <div><dt>缓存后端</dt><dd>{{ info?.cache || '—' }}</dd></div>
        <div><dt>定时任务</dt><dd>{{ info?.scheduler_jobs ?? 0 }} 个</dd></div>
        <div class="fact-wide"><dt>配置文件</dt><dd class="mono">{{ info?.config_path || '—' }}</dd></div>
      </dl>
    </div>

    <div class="yx-card" v-loading="configLoading">
      <div class="yx-card-title">
        <h3>常用参数</h3>
        <el-tag v-if="auth.isOwner" size="small" type="warning" effect="plain">
          部分修改需重启
        </el-tag>
      </div>

      <el-alert
        v-if="!auth.isOwner"
        title="仅超级主人可修改系统配置"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />

      <el-form :model="configForm" label-position="top" :disabled="!auth.isOwner">
        <div class="param-section">
          <div class="param-title">
            <h4>限流</h4>
            <span class="muted small">发送频率、推送上限与随机延时（秒）</span>
          </div>
          <div class="param-grid">
            <el-form-item label="单用户每分钟">
              <el-input-number
                v-model="configForm.rate_limit.per_user_per_minute"
                :min="0"
                :max="9999"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="单群每分钟">
              <el-input-number
                v-model="configForm.rate_limit.per_group_per_minute"
                :min="0"
                :max="9999"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="单账号每分钟">
              <el-input-number
                v-model="configForm.rate_limit.per_account_per_minute"
                :min="0"
                :max="9999"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="推送每分钟">
              <el-input-number
                v-model="configForm.rate_limit.push_per_minute"
                :min="0"
                :max="9999"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="推送每日上限">
              <el-input-number
                v-model="configForm.rate_limit.push_daily_limit"
                :min="0"
                :max="999999"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="随机延时下限">
              <el-input-number
                v-model="configForm.rate_limit.random_delay_min"
                :min="0"
                :max="60"
                :step="0.1"
                :precision="1"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="随机延时上限">
              <el-input-number
                v-model="configForm.rate_limit.random_delay_max"
                :min="0"
                :max="60"
                :step="0.1"
                :precision="1"
                controls-position="right"
              />
            </el-form-item>
          </div>
        </div>

        <div class="param-section">
          <div class="param-title">
            <h4>对话</h4>
            <span class="muted small">上下文、长期记忆与失败兜底</span>
          </div>
          <div class="param-grid">
            <el-form-item label="启用上下文">
              <div class="switch-line">
                <el-switch v-model="configForm.dispatch.context_enabled" aria-label="启用上下文" />
                <span class="muted small">关闭后为一问一答模式</span>
              </div>
            </el-form-item>
            <el-form-item label="记忆注入条数">
              <el-input-number
                v-model="configForm.memory.top_k"
                :min="0"
                :max="50"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="上下文缓存 TTL（秒）">
              <el-input-number
                v-model="configForm.redis.context_ttl"
                :min="0"
                :max="86400"
                controls-position="right"
              />
              <span class="muted small">仅控制缓存；过期或重启后从数据库恢复会话。</span>
            </el-form-item>
            <el-form-item label="摘要窗口轮数">
              <el-input-number
                v-model="configForm.redis.context_max_rounds"
                :min="0"
                :max="200"
                controls-position="right"
              />
              <span class="muted small">0 按模型容量自动保留；摘要后原始对话仍留档。</span>
            </el-form-item>
            <el-form-item label="LLM 失败兜底话术" class="span-2">
              <el-input
                v-model="configForm.dispatch.fallback_reply"
                type="textarea"
                :rows="2"
                resize="none"
                placeholder="模型调用失败时发送的兜底回复"
              />
            </el-form-item>
          </div>
        </div>

        <div class="param-section">
          <div class="param-title">
            <h4>调度</h4>
            <span class="muted small">自动备份与日志保留策略</span>
          </div>
          <div class="param-grid">
            <el-form-item label="备份间隔（小时）">
              <el-input-number
                v-model="configForm.scheduler.backup_interval_hours"
                :min="0"
                :max="720"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="日志保留天数">
              <el-input-number
                v-model="configForm.scheduler.log_retention_days"
                :min="1"
                :max="3650"
                controls-position="right"
              />
            </el-form-item>
            <el-form-item label="备份保留份数">
              <el-input-number
                v-model="configForm.scheduler.backup_keep"
                :min="1"
                :max="100"
                controls-position="right"
              />
            </el-form-item>
          </div>
        </div>
      </el-form>

      <div class="form-actions">
        <span class="muted small">保存后部分配置需重启服务生效</span>
        <el-button
          type="primary"
          :loading="savingConfig"
          :disabled="!auth.isOwner"
          @click="saveConfig"
        >
          保存参数
        </el-button>
      </div>
    </div>

    <div class="yx-grid yx-grid-2">
      <div class="yx-card" v-loading="backupsLoading">
        <div class="yx-card-title">
          <h3>数据备份</h3>
          <div class="title-actions">
            <span class="muted small">共 {{ backups.length }} 份</span>
            <el-button
              v-if="auth.isOwner"
              type="primary"
              size="small"
              :icon="FolderAdd"
              :loading="backupCreating"
              @click="handleBackup"
            >
              立即备份
            </el-button>
          </div>
        </div>

        <el-table :data="backups" row-key="name" size="small" border>
          <el-table-column label="名称" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ formatBytes(row.size) }}</template>
          </el-table-column>
          <el-table-column label="时间" width="168">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column v-if="auth.isOwner" label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :loading="restoringName === row.name"
                @click="handleRestore(row)"
              >
                恢复
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无备份" :image-size="80" />
          </template>
        </el-table>

        <div v-if="!auth.isOwner" class="yx-hint" style="margin-top: 12px">
          备份与恢复仅超级主人可操作。
        </div>
      </div>

      <div class="yx-card" v-loading="jobsLoading">
        <div class="yx-card-title">
          <h3>定时任务</h3>
          <el-button size="small" :icon="Refresh" :loading="jobsLoading" @click="loadJobs">
            刷新
          </el-button>
        </div>

        <el-table :data="jobs" row-key="id" size="small" border>
          <el-table-column label="任务 ID" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.id }}</span>
            </template>
          </el-table-column>
          <el-table-column label="下次执行" width="168">
            <template #default="{ row }">{{ formatDateTime(row.next_run_time) }}</template>
          </el-table-column>
          <el-table-column label="触发器" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.trigger || '—' }}</span>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无定时任务" :image-size="80" />
          </template>
        </el-table>
      </div>
    </div>

    <div v-if="auth.isOwner" class="yx-card" v-loading="usersLoading">
      <div class="yx-card-title">
        <h3>后台账号</h3>
        <el-button type="primary" size="small" :icon="Plus" @click="openCreateUser">
          新建账号
        </el-button>
      </div>

      <el-table :data="users" row-key="id" size="small" border>
        <el-table-column label="用户名" min-width="150">
          <template #default="{ row }">
            <span class="mono">{{ row.username }}</span>
            <el-tag
              v-if="row.id === auth.user?.id"
              size="small"
              effect="plain"
              style="margin-left: 6px"
            >
              当前
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="昵称" min-width="140">
          <template #default="{ row }">{{ row.nickname || '—' }}</template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag
              size="small"
              effect="plain"
              :type="row.role === 'owner' ? 'warning' : 'info'"
            >
              {{ row.role === 'owner' ? '超级主人' : '管理员' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <div class="switch-cell">
              <el-switch
                v-model="row.is_active"
                :aria-label="`启用后台账号 ${row.username}`"
                :loading="togglingId === row.id"
                :disabled="row.id === auth.user?.id"
                @change="(value) => toggleUserActive(row, value)"
              />
              <span class="muted small">{{ row.is_active ? '启用' : '禁用' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="最后登录" width="168">
          <template #default="{ row }">{{ formatDateTime(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openResetPassword(row)">
              重置密码
            </el-button>
            <el-button
              link
              type="danger"
              :disabled="row.id === auth.user?.id"
              @click="handleDeleteUser(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无后台账号" :image-size="80" />
        </template>
      </el-table>
    </div>

    <div class="yx-card">
      <div class="yx-card-title">
        <h3>日志清理</h3>
        <el-tag size="small" effect="plain">仅超级主人</el-tag>
      </div>

      <div class="cleanup-line">
        <span class="muted small">删除</span>
        <el-input-number
          v-model="cleanupDays"
          aria-label="日志保留天数"
          :min="1"
          :max="3650"
          :disabled="!auth.isOwner"
          controls-position="right"
          style="width: 140px"
        />
        <span class="muted small">天之前的全部日志</span>
        <el-button
          type="danger"
          plain
          :loading="cleanupLoading"
          :disabled="!auth.isOwner"
          @click="handleCleanup"
        >
          清理日志
        </el-button>
      </div>

      <div v-if="!auth.isOwner" class="yx-hint" style="margin-top: 12px">
        日志清理仅超级主人可执行。
      </div>

      <div v-if="cleanupResult" class="cleanup-stats">
        <div v-for="(label, key) in cleanupLabels" :key="key" class="cleanup-stat">
          <span class="muted">{{ label }}</span>
          <strong>{{ cleanupResult[key] || 0 }}</strong>
        </div>
      </div>
    </div>

    <el-dialog v-model="userDialogVisible" title="新建后台账号" width="460px">
      <el-form ref="userFormRef" :model="userForm" :rules="userRules" label-position="top">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="userForm.username" placeholder="2-32 位，用于登录" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="userForm.password"
            type="password"
            show-password
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="userForm.role" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="超级主人" value="owner" />
          </el-select>
        </el-form-item>
        <el-form-item label="昵称" prop="nickname">
          <el-input v-model="userForm.nickname" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="userCreating" @click="submitCreateUser">
          创建
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="passwordDialogVisible" title="重置密码" width="420px">
      <div class="yx-hint">
        正在为账号「{{ passwordTarget?.username || '—' }}」设置新密码，保存后立即生效。
      </div>
      <el-form
        ref="passwordFormRef"
        :model="passwordForm"
        :rules="passwordRules"
        label-position="top"
        style="margin-top: 16px"
      >
        <el-form-item label="新密码" prop="password">
          <el-input
            v-model="passwordForm.password"
            type="password"
            show-password
            placeholder="至少 6 位"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="passwordSubmitting" @click="submitResetPassword">
          确认重置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderAdd, Plus, Refresh } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import { createUser, deleteUser, listUsers, updateUser } from '@/api/auth'
import { cleanupLogs } from '@/api/log'
import {
  createBackup,
  getConfig,
  getSystemInfo,
  listBackups,
  listJobs,
  restoreBackup,
  updateConfig,
} from '@/api/system'
import { useAuthStore } from '@/stores/auth'
import { formatBytes, formatDateTime } from '@/utils/format'

const auth = useAuthStore()

const info = ref(null)
const infoLoading = ref(false)
const configLoading = ref(false)
const savingConfig = ref(false)
const refreshing = ref(false)

const backups = ref([])
const backupsLoading = ref(false)
const backupCreating = ref(false)
const restoringName = ref('')

const jobs = ref([])
const jobsLoading = ref(false)

const users = ref([])
const usersLoading = ref(false)
const togglingId = ref('')

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

const configForm = reactive({
  rate_limit: {
    per_user_per_minute: 12,
    per_group_per_minute: 40,
    per_account_per_minute: 60,
    push_per_minute: 5,
    push_daily_limit: 50,
    random_delay_min: 0.3,
    random_delay_max: 1.2,
  },
  dispatch: {
    context_enabled: true,
    fallback_reply: '',
  },
  memory: {
    top_k: 5,
  },
  redis: {
    context_ttl: 600,
    context_max_rounds: 0,
  },
  scheduler: {
    backup_interval_hours: 24,
    log_retention_days: 30,
    backup_keep: 7,
  },
})

function numberOr(value, fallback) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function applyConfig(data) {
  const rate = data.rate_limit || {}
  configForm.rate_limit.per_user_per_minute = numberOr(rate.per_user_per_minute, 12)
  configForm.rate_limit.per_group_per_minute = numberOr(rate.per_group_per_minute, 40)
  configForm.rate_limit.per_account_per_minute = numberOr(rate.per_account_per_minute, 60)
  configForm.rate_limit.push_per_minute = numberOr(rate.push_per_minute, 5)
  configForm.rate_limit.push_daily_limit = numberOr(rate.push_daily_limit, 50)
  configForm.rate_limit.random_delay_min = numberOr(rate.random_delay_min, 0.3)
  configForm.rate_limit.random_delay_max = numberOr(rate.random_delay_max, 1.2)

  const dispatch = data.dispatch || {}
  configForm.dispatch.context_enabled = Boolean(dispatch.context_enabled ?? true)
  configForm.dispatch.fallback_reply = dispatch.fallback_reply ?? ''

  const memory = data.memory || {}
  configForm.memory.top_k = numberOr(memory.top_k, 5)

  const redis = data.redis || {}
  configForm.redis.context_ttl = numberOr(redis.context_ttl, 600)
  configForm.redis.context_max_rounds = numberOr(redis.context_max_rounds, 0)

  const scheduler = data.scheduler || {}
  configForm.scheduler.backup_interval_hours = numberOr(scheduler.backup_interval_hours, 24)
  configForm.scheduler.log_retention_days = numberOr(scheduler.log_retention_days, 30)
  configForm.scheduler.backup_keep = numberOr(scheduler.backup_keep, 7)
}

async function loadInfo() {
  infoLoading.value = true
  try {
    info.value = await getSystemInfo()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    infoLoading.value = false
  }
}

async function loadConfig() {
  configLoading.value = true
  try {
    const data = await getConfig()
    applyConfig(data || {})
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    configLoading.value = false
  }
}

async function loadBackups() {
  backupsLoading.value = true
  try {
    const data = await listBackups()
    backups.value = Array.isArray(data) ? data : []
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    backupsLoading.value = false
  }
}

async function loadJobs() {
  jobsLoading.value = true
  try {
    const data = await listJobs()
    jobs.value = Array.isArray(data) ? data : []
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    jobsLoading.value = false
  }
}

async function loadUsers() {
  if (!auth.isOwner) return
  usersLoading.value = true
  try {
    const data = await listUsers()
    users.value = Array.isArray(data) ? data : []
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    usersLoading.value = false
  }
}

async function loadAll() {
  refreshing.value = true
  try {
    await Promise.allSettled([
      loadInfo(),
      loadConfig(),
      loadBackups(),
      loadJobs(),
      auth.isOwner ? loadUsers() : Promise.resolve(),
    ])
  } finally {
    refreshing.value = false
  }
}

async function saveConfig() {
  if (!auth.isOwner) return
  savingConfig.value = true
  try {
    await updateConfig({
      rate_limit: {
        per_user_per_minute: configForm.rate_limit.per_user_per_minute ?? 12,
        per_group_per_minute: configForm.rate_limit.per_group_per_minute ?? 40,
        per_account_per_minute: configForm.rate_limit.per_account_per_minute ?? 60,
        push_per_minute: configForm.rate_limit.push_per_minute ?? 5,
        push_daily_limit: configForm.rate_limit.push_daily_limit ?? 50,
        random_delay_min: configForm.rate_limit.random_delay_min ?? 0.3,
        random_delay_max: configForm.rate_limit.random_delay_max ?? 1.2,
      },
      dispatch: {
        context_enabled: configForm.dispatch.context_enabled,
        fallback_reply: configForm.dispatch.fallback_reply ?? '',
      },
      memory: {
        top_k: configForm.memory.top_k ?? 5,
      },
      redis: {
        context_ttl: configForm.redis.context_ttl ?? 600,
        context_max_rounds: configForm.redis.context_max_rounds ?? 0,
      },
      scheduler: {
        backup_interval_hours: configForm.scheduler.backup_interval_hours ?? 24,
        log_retention_days: configForm.scheduler.log_retention_days ?? 30,
        backup_keep: configForm.scheduler.backup_keep ?? 7,
      },
    })
    ElMessage.success('系统配置已保存，部分配置需重启服务生效')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    savingConfig.value = false
  }
}

async function handleBackup() {
  backupCreating.value = true
  try {
    const data = await createBackup()
    ElMessage.success(`备份完成：${data.file || '已生成备份文件'}`)
    await loadBackups()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    backupCreating.value = false
  }
}

async function handleRestore(row) {
  try {
    await ElMessageBox.confirm(
      `将使用备份「${row.name}」覆盖当前数据库，恢复期间请勿操作，是否继续？`,
      '恢复数据库',
      { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  restoringName.value = row.name
  try {
    const data = await restoreBackup(row.name)
    ElMessage.success(data.message || '恢复完成，建议重启服务')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    restoringName.value = ''
  }
}

const userDialogVisible = ref(false)
const userCreating = ref(false)
const userFormRef = ref(null)
const userForm = reactive({
  username: '',
  password: '',
  role: 'admin',
  nickname: '',
})
const userRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 32, message: '用户名长度为 2-32 位', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 128, message: '密码至少 6 位', trigger: 'blur' },
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function openCreateUser() {
  Object.assign(userForm, { username: '', password: '', role: 'admin', nickname: '' })
  userDialogVisible.value = true
  nextTick(() => userFormRef.value?.clearValidate())
}

async function submitCreateUser() {
  if (!userFormRef.value) return
  try {
    await userFormRef.value.validate()
  } catch {
    return
  }
  const username = userForm.username.trim()
  if (!username) {
    ElMessage.warning('请输入用户名')
    return
  }
  userCreating.value = true
  try {
    await createUser({
      username,
      password: userForm.password,
      role: userForm.role,
      nickname: userForm.nickname.trim(),
    })
    ElMessage.success('后台账号已创建')
    userDialogVisible.value = false
    await loadUsers()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    userCreating.value = false
  }
}

const passwordDialogVisible = ref(false)
const passwordSubmitting = ref(false)
const passwordFormRef = ref(null)
const passwordTarget = ref(null)
const passwordForm = reactive({ password: '' })
const passwordRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 128, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

function openResetPassword(row) {
  passwordTarget.value = row
  passwordForm.password = ''
  passwordDialogVisible.value = true
  nextTick(() => passwordFormRef.value?.clearValidate())
}

async function submitResetPassword() {
  if (!passwordFormRef.value || !passwordTarget.value) return
  try {
    await passwordFormRef.value.validate()
  } catch {
    return
  }
  passwordSubmitting.value = true
  try {
    await updateUser(passwordTarget.value.id, { password: passwordForm.password })
    ElMessage.success(`已重置「${passwordTarget.value.username}」的密码`)
    passwordDialogVisible.value = false
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    passwordSubmitting.value = false
  }
}

async function toggleUserActive(row, value) {
  togglingId.value = row.id
  try {
    await updateUser(row.id, { is_active: value })
    ElMessage.success(value ? `已启用「${row.username}」` : `已禁用「${row.username}」`)
  } catch {
    row.is_active = !value
  } finally {
    togglingId.value = ''
  }
}

async function handleDeleteUser(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${row.username}」吗？删除后不可恢复。`,
      '删除后台账号',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteUser(row.id)
    ElMessage.success('后台账号已删除')
    await loadUsers()
  } catch {
    // 错误提示由请求拦截器统一处理
  }
}

async function handleCleanup() {
  if (!auth.isOwner) return
  if (!cleanupDays.value) {
    ElMessage.warning('请输入保留天数')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将删除 ${cleanupDays.value} 天之前的全部日志，操作不可撤销，是否继续？`,
      '清理日志',
      { type: 'warning', confirmButtonText: '开始清理', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  cleanupLoading.value = true
  try {
    const data = await cleanupLogs(cleanupDays.value)
    cleanupResult.value = data.deleted || {}
    ElMessage.success(data.message || '日志清理完成')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    cleanupLoading.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.system-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 28px;
  margin: 0;
}

.system-facts > div {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 16px;
  padding: 12px 0;
  border-bottom: 1px solid var(--yx-line);
  font-size: 13px;
}

.system-facts .fact-wide { grid-column: 1 / -1; }
.system-facts dt { color: var(--yx-muted); }
.system-facts dd { margin: 0; color: var(--yx-text-2); overflow-wrap: anywhere; }
.system-facts > div:last-child { border-bottom: 0; padding-bottom: 0; }

.param-section {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  gap: 24px;
}

.param-section + .param-section {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid var(--yx-line);
}

.param-title {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 6px;
}

.param-title h4 {
  margin: 0;
  color: var(--yx-text);
  font-size: 14px;
  font-weight: 600;
}

.param-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 16px;
}

.param-grid .span-2 {
  grid-column: span 2;
}

.param-grid :deep(.el-input-number) {
  width: 100%;
}

.switch-line {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 32px;
}

.switch-line .el-switch { flex: none; }

.form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
  padding-top: 20px;
  border-top: 1px solid var(--yx-line);
}

.title-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.switch-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cleanup-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.cleanup-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.cleanup-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--yx-line);
  border-radius: 10px;
  background: var(--yx-elevated);
  font-size: 12px;
}

.cleanup-stat strong {
  color: var(--yx-text);
  font-size: 17px;
}

@media (max-width: 1100px) {
  .param-section { grid-template-columns: 1fr; gap: 16px; }
  .param-title { flex-direction: row; align-items: baseline; justify-content: space-between; }
}

@media (max-width: 900px) {
  .param-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 620px) {
  .system-facts { grid-template-columns: 1fr; }

  .param-grid {
    grid-template-columns: 1fr;
  }

  .param-grid .span-2 {
    grid-column: auto;
  }

  .param-title {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
}
</style>
