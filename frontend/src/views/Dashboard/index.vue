<template>
  <div class="yx-page dashboard-page" :aria-busy="loading">
    <PageHeader title="总览" description="你的月夜工作台，连接、对话与记忆都在这里。">
      <span class="refresh-time" role="status">{{ updatedAt ? `更新于 ${updatedAt}` : '正在获取运行状态' }}</span>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新数据</el-button>
    </PageHeader>

    <el-alert v-if="loadError" :title="loadError" type="warning" show-icon :closable="false" />
    <el-alert v-if="dashboard?.service.database === 'down'" title="数据库连接异常，请检查数据库配置或服务日志" type="error" show-icon :closable="false" />

    <section class="overview-board" aria-labelledby="welcome-title">
      <div class="lunar-welcome">
        <div class="lunar-welcome-copy">
          <h2 id="welcome-title">月下叙话，记忆留存。</h2>
          <p>连接你的账号与机器人，让对话从这里开始。</p>
        </div>
        <el-button type="primary" @click="router.push('/accounts')">{{ dashboard?.accounts.total ? '管理连接' : '添加第一个连接' }}<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
      </div>
      <img :src="moon" class="lunar-welcome-moon" width="280" height="280" alt="" fetchpriority="high" />
      <div class="dashboard-stats">
        <StatCard label="在线连接" :value="dashboard ? `${dashboard.accounts.online} / ${dashboard.accounts.total}` : '—'" icon="Iphone" note="在线 / 全部账号与机器人" />
        <StatCard label="今日消息" :value="dashboard?.today.messages ?? '—'" icon="ChatDotRound" note="接收与发送消息总量" />
        <StatCard label="AI 调用" :value="dashboard?.today.ai_calls ?? '—'" icon="Cpu" note="今日模型请求次数" />
        <StatCard label="今日 Tokens" :value="dashboard?.today.tokens?.toLocaleString('zh-CN') ?? '—'" icon="Coin" note="AI 对话日志中的输入与输出" />
      </div>
    </section>

    <div class="dashboard-workspace">
      <div class="dashboard-primary">
      <section class="yx-card today-card" aria-labelledby="today-title">
        <div class="yx-card-title"><div><h3 id="today-title">今日明细</h3><p class="section-description">消息流向与模型用量</p></div><router-link to="/logs" class="section-link">查看日志<el-icon><ArrowRight /></el-icon></router-link></div>
        <div class="message-split">
          <div><span><i class="legend-in"></i>接收消息</span><strong>{{ dashboard?.today.messages_in ?? '—' }}</strong></div>
          <div><span><i class="legend-out"></i>发送消息</span><strong>{{ dashboard?.today.messages_out ?? '—' }}</strong></div>
        </div>
        <div class="message-bar" :class="{ 'is-empty': !dashboard?.today.messages }" aria-hidden="true"><span :style="{ width: incomingPercent + '%' }"></span></div>
        <p v-if="dashboard?.today.messages === 0" class="message-empty">今天还没有消息，连接账号后即可开始对话。</p>
        <div class="usage-grid">
          <div>
            <div class="detail-row"><span>输入 Tokens</span><strong>{{ dashboard?.today.prompt_tokens?.toLocaleString('zh-CN') ?? '—' }}</strong></div>
            <div class="detail-row"><span>输出 Tokens</span><strong>{{ dashboard?.today.completion_tokens?.toLocaleString('zh-CN') ?? '—' }}</strong></div>
          </div>
          <div>
            <div class="detail-row"><span>搜索调用</span><strong>{{ dashboard?.today.search_calls ?? '—' }}</strong></div>
            <div class="detail-row"><span>推送成功</span><strong>{{ dashboard?.today.push_success ?? '—' }}</strong></div>
          </div>
        </div>
        <p class="detail-note">Tokens 仅统计 AI 对话日志中的接口返回用量；未返回用量时记为 0，不含记忆提取、主动推送和模型测试。</p>
        <div class="failure-summary">
          <div class="detail-row"><span>AI 调用失败</span><strong :class="{ 'yx-danger-text': dashboard?.today.ai_failed > 0 }">{{ dashboard?.today.ai_failed ?? '—' }}</strong></div>
          <div class="detail-row"><span>推送失败</span><strong :class="{ 'yx-danger-text': dashboard?.today.push_failed > 0 }">{{ dashboard?.today.push_failed ?? '—' }}</strong></div>
        </div>
        <p class="detail-note">失败次数持续增加时，可在 AI 日志或推送日志中查看原因。</p>
      </section>

      <section class="yx-card quick-card" aria-labelledby="quick-title">
        <div class="yx-card-title"><h3 id="quick-title">快捷操作</h3><span class="section-note">常用工作入口</span></div>
        <div class="quick-grid">
          <router-link v-for="action in quickActions" :key="action.path" :to="action.path" class="quick-item">
            <el-icon :size="18"><component :is="action.icon" /></el-icon>
            <span><strong>{{ action.label }}</strong><small>{{ action.desc }}</small></span>
            <el-icon class="quick-arrow"><ArrowRight /></el-icon>
          </router-link>
        </div>
      </section>
      </div>

      <div class="dashboard-secondary">
      <section class="yx-card runtime-card" aria-labelledby="runtime-title">
        <div class="yx-card-title">
          <h3 id="runtime-title">运行状态</h3>
          <span class="section-note">每 30 秒自动刷新</span>
        </div>
        <div class="service-list">
          <div class="service-row">
            <span class="service-icon"><el-icon><Coin /></el-icon></span>
            <span class="service-name">数据库<span>对话与配置持久化</span></span>
            <el-tag size="small" effect="plain" :type="!dashboard ? 'info' : dashboard.service.database === 'up' ? 'success' : 'danger'">{{ !dashboard ? '待检测' : dashboard.service.database === 'up' ? '已连接' : '不可用' }}</el-tag>
          </div>
          <div class="service-row">
            <span class="service-icon"><el-icon><Box /></el-icon></span>
            <span class="service-name">缓存后端<span>{{ !dashboard ? '正在读取' : dashboard.service.cache === 'redis' ? 'Redis' : '进程内缓存' }}</span></span>
            <el-tag size="small" effect="plain" type="info">{{ dashboard ? '已启用' : '待检测' }}</el-tag>
          </div>
          <div class="service-row">
            <span class="service-icon"><el-icon><Timer /></el-icon></span>
            <span class="service-name">后台调度<span>私聊惦记轮询与自动维护</span></span>
            <el-tag size="small" effect="plain" :type="!dashboard ? 'info' : dashboard.service.scheduler === 'running' ? 'success' : 'warning'">{{ !dashboard ? '待检测' : dashboard.service.scheduler === 'running' ? '运行中' : '已停止' }}</el-tag>
          </div>
        </div>
      </section>

      <section class="workspace-resources" aria-label="会话与记忆">
        <router-link to="/contexts"><span>上下文会话</span><strong>{{ dashboard?.context.sessions ?? '—' }}</strong><el-icon><ArrowRight /></el-icon></router-link>
        <router-link to="/memory"><span>长期记忆</span><strong>{{ dashboard?.memory.total ?? '—' }}</strong><el-icon><ArrowRight /></el-icon></router-link>
        <router-link to="/push"><span>允许主动消息 / 私聊用户</span><strong>{{ dashboard ? `${dashboard.push.enabled_tasks} / ${dashboard.push.total_tasks}` : '—' }}</strong><el-icon><ArrowRight /></el-icon></router-link>
      </section>

      <section class="yx-card guide-card" aria-labelledby="guide-title">
        <div class="yx-card-title"><h3 id="guide-title">接入指引</h3><span class="section-note">完成你的第一个对话</span></div>
        <ol class="setup-steps">
          <li v-for="(step, index) in steps" :key="step.title">
            <span class="step-index">{{ index + 1 }}</span>
            <div><router-link v-if="step.path" :to="step.path">{{ step.title }}<el-icon><ArrowRight /></el-icon></router-link><strong v-else>{{ step.title }}</strong><p>{{ step.desc }}</p></div>
          </li>
        </ol>
      </section>
      </div>
    </div>

    <footer class="system-line">
      <span>月叙 <span class="mono">{{ info?.version || '—' }}</span></span>
      <span>Python {{ info?.python || '—' }}</span>
      <span class="system-location" :title="info?.database">数据库 {{ info?.database || '—' }}</span>
      <span class="system-config" :title="info?.config_path">配置 {{ info?.config_path || '—' }}</span>
    </footer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Box, Coin, Refresh, Timer } from '@element-plus/icons-vue'
import moon from '@/assets/lunar-moon.webp'

import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import { getDashboard, getSystemInfo } from '@/api/system'

const router = useRouter()
const dashboard = ref(null)
const info = ref(null)
const loading = ref(false)
const loadError = ref('')
const updatedAt = ref('')
let timer = null
const incomingPercent = computed(() => {
  const today = dashboard.value?.today
  return today?.messages ? today.messages_in / today.messages * 100 : 0
})
const quickActions = [
  { path: '/accounts', label: '账号与机器人', desc: '扫码登录 · 机器人接入', icon: 'Iphone' },
  { path: '/models', label: '模型配置', desc: '接口参数 · 默认模型', icon: 'Cpu' },
  { path: '/characters', label: '人设管理', desc: '性格语气 · 提示词', icon: 'User' },
  { path: '/push', label: '私聊惦记', desc: '用户选择 · 推送留存', icon: 'AlarmClock' },
  { path: '/emojis', label: '表情库', desc: '上传表情 · 标签权重', icon: 'Picture' },
  { path: '/system', label: '系统设置', desc: '备份数据 · 系统参数', icon: 'Setting' },
]
const steps = [
  { title: '配置模型', path: '/models', desc: '填写模型接口与 Key，并测试连通性。' },
  { title: '连接账号或机器人', path: '/accounts', desc: '选择个人账号、QQ 官方机器人或微信 ClawBot。' },
  { title: '选择人设', path: '/characters', desc: '设置全局人设，或为账号、群组独立绑定。' },
  { title: '私聊或 @ 唤醒', desc: '私聊直接对话；群聊 @机器人，或使用唤醒词。' },
]

async function load() {
  if (loading.value) return
  loading.value = true
  try {
    const [dash, meta] = await Promise.allSettled([
      getDashboard(), info.value ? Promise.resolve(info.value) : getSystemInfo(),
    ])
    if (dash.status === 'fulfilled') {
      dashboard.value = dash.value
      updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
      loadError.value = ''
    } else {
      loadError.value = dashboard.value ? '刷新失败，当前保留上次数据。请检查连接后重试。' : '暂时无法读取运行数据，请检查连接后点击刷新。'
    }
    if (meta.status === 'fulfilled') info.value = meta.value
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  timer = window.setInterval(load, 30000)
})
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.refresh-time, .section-note { color: var(--yx-muted); font-size: 12px; }
.overview-board { display: grid; grid-template-columns: minmax(0, 1fr) 224px; grid-template-areas: "welcome moon" "stats stats"; align-items: center; gap: 28px 36px; padding: 0; }
.lunar-welcome { grid-area: welcome; display: flex; flex-direction: column; align-items: flex-start; gap: 20px; }
.lunar-welcome-moon { grid-area: moon; width: 224px; height: 224px; object-fit: contain; }
.lunar-welcome-copy { min-width: 0; }
.lunar-welcome h2 { margin: 0; font-family: var(--yx-heading-font); font-size: 30px; font-weight: 400; line-height: 1.5; letter-spacing: .04em; color: var(--yx-text); }
.lunar-welcome p { color: var(--yx-muted); margin: 10px 0 0; font-size: 14px; line-height: 1.7; }
.dashboard-stats { grid-area: stats; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--yx-line); border-radius: var(--yx-radius); background: var(--yx-card); overflow: hidden; }
.dashboard-stats :deep(.yx-stat) { padding: 22px 24px; border: 0; border-radius: 0; background: transparent; }
.dashboard-stats > :not(:last-child) { border-right: 1px solid var(--yx-line); }
.dashboard-stats :deep(.yx-stat-value) { font-size: 30px; margin-top: 12px; overflow-wrap: anywhere; }
.dashboard-stats :deep(.yx-stat-icon) { font-size: 16px; top: 25px; right: 24px; }
.dashboard-stats > :first-child :deep(.yx-stat-value) { color: var(--yx-accent); }
.dashboard-stats :deep(.yx-stat-note) { font-size: 12px; margin-top: 10px; }
.dashboard-workspace { display: grid; grid-template-columns: minmax(0, 1fr) 320px; align-items: start; gap: 24px; }
.dashboard-workspace > * { min-width: 0; }
.dashboard-primary, .dashboard-secondary { display: flex; flex-direction: column; gap: 24px; }
.today-card { grid-area: today; }
.runtime-card { grid-area: runtime; }
.quick-card { grid-area: quick; }
.guide-card { grid-area: guide; background: transparent; }
.section-description { margin: 5px 0 0; color: var(--yx-muted); font-size: 12px; }
.service-list { display: flex; flex-direction: column; }
.service-row { display: flex; align-items: center; gap: 10px; padding: 13px 0; }
.service-row + .service-row { border-top: 1px solid var(--yx-line); }
.service-row:last-child { padding-bottom: 0; }
.service-icon { display: grid; place-items: center; width: 28px; height: 28px; flex: none; color: var(--yx-text-2); font-size: 16px; }
.service-name { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 4px; font-size: 13px; }
.service-name > span { color: var(--yx-muted); font-size: 12px; line-height: 1.6; }
.workspace-resources { grid-area: resources; padding: 2px 0; }
.workspace-resources a { display: flex; align-items: center; gap: 12px; padding: 14px 8px; color: var(--yx-text-2); border-bottom: 1px solid var(--yx-line); }
.workspace-resources a:first-child { padding-top: 0; }
.workspace-resources a:last-child { border-bottom: 0; padding-bottom: 0; }
.workspace-resources a > span { flex: 1; min-width: 0; font-size: 12px; }
.workspace-resources strong { color: var(--yx-text); font-size: 18px; font-weight: 500; font-variant-numeric: tabular-nums; }
.workspace-resources .el-icon { font-size: 12px; color: var(--yx-muted); }
.workspace-resources a:hover, .workspace-resources a:hover strong, .workspace-resources a:hover .el-icon { color: var(--yx-accent); }
.quick-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 24px; }
.quick-item { display: flex; align-items: center; gap: 12px; min-height: 76px; padding: 15px 8px; color: var(--yx-muted); border-bottom: 1px solid var(--yx-line); transition: background-color .15s ease, color .15s ease; }
.quick-item:nth-last-child(-n+2) { border-bottom: 0; }
.quick-item > .el-icon:first-child { flex: none; }
.quick-item > span { flex: 1; min-width: 0; }
.quick-item strong { display: block; color: var(--yx-text); font-size: 13px; font-weight: 500; }
.quick-item small { display: block; color: var(--yx-muted); font-size: 12px; margin-top: 4px; }
.quick-arrow { font-size: 12px; color: var(--yx-muted); }
.quick-item:hover, .quick-item:hover strong, .quick-item:hover .quick-arrow { color: var(--yx-accent); }
.quick-item:hover { background: var(--yx-elevated); }
.message-split { display: grid; grid-template-columns: 1fr 1fr; padding-top: 8px; }
.message-split > div { display: flex; flex-direction: column; gap: 12px; }
.message-split span { display: flex; align-items: center; gap: 8px; color: var(--yx-text-2); font-size: 12px; }
.message-split i { width: 7px; height: 7px; border-radius: 2px; }
.legend-in { background: var(--yx-accent); }
.legend-out { background: var(--yx-muted); }
.message-split strong { font-size: 32px; font-weight: 500; line-height: 1.3; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.message-bar { height: 8px; border-radius: 3px; background: var(--yx-muted); margin: 22px 0; overflow: hidden; }
.message-bar span { display: block; height: 100%; background: var(--yx-accent); }
.message-bar.is-empty { background: var(--yx-elevated); }
.message-empty { color: var(--yx-muted); font-size: 12px; margin: 0 0 14px; }
.usage-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.usage-grid > :last-child { padding-left: 24px; border-left: 1px solid var(--yx-line); }
.detail-row { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; font-size: 12px; padding: 8px 0; color: var(--yx-text-2); }
.detail-row strong { font-size: 15px; font-weight: 500; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; text-align: right; }
.failure-summary { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; border-top: 1px solid var(--yx-line); margin-top: 20px; padding-top: 10px; }
.detail-note { margin: 12px 0 0; color: var(--yx-muted); font-size: 12px; line-height: 1.8; }
.section-link { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.setup-steps { display: flex; flex-direction: column; gap: 18px; list-style: none; margin: 0; padding: 2px 0; }
.setup-steps li { display: flex; gap: 12px; position: relative; }
.setup-steps li:not(:last-child)::after { content: ''; position: absolute; width: 1px; background: var(--yx-line); left: 12px; top: 31px; bottom: -12px; }
.step-index { flex: none; width: 25px; height: 25px; border: 1px solid var(--yx-line); border-radius: 7px; display: grid; place-items: center; font-size: 11px; color: var(--yx-text-2); }
.setup-steps a, .setup-steps strong { display: flex; align-items: center; gap: 8px; color: var(--yx-text); font-size: 13px; font-weight: 500; line-height: 25px; }
.setup-steps a:hover { color: var(--yx-accent); }
.setup-steps .el-icon { color: var(--yx-muted); font-size: 11px; }
.setup-steps p { color: var(--yx-muted); font-size: 12px; margin: 4px 0 0; line-height: 1.7; }
.system-line { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 24px; padding: 0 0 8px; font-size: 12px; color: var(--yx-muted); }
.system-line > span { max-width: 100%; overflow-wrap: anywhere; }
.system-line .mono { font-size: inherit; }
.system-config { margin-left: auto; }
@media (max-width: 1200px) {
  .overview-board { grid-template-columns: minmax(0, 1fr) 200px; gap: 24px; }
  .lunar-welcome-moon { width: 200px; height: 200px; }
  .lunar-welcome h2 { font-size: 26px; }
  .dashboard-workspace { grid-template-columns: minmax(0, 1fr) 290px; }
  .dashboard-stats :deep(.yx-stat) { padding: 16px; }
  .usage-grid, .failure-summary { gap: 18px; }
  .usage-grid > :last-child { padding-left: 18px; }
  .quick-grid { column-gap: 14px; }
  .quick-arrow { display: none; }
}
@media (max-width: 1050px) {
  .overview-board { grid-template-columns: minmax(0, 1fr) 200px; grid-template-areas: "welcome moon" "stats stats"; }
  .lunar-welcome-moon { width: 200px; height: 200px; }
  .dashboard-workspace { grid-template-columns: 1fr 1fr; grid-template-areas: "today today" "runtime guide" "resources resources" "quick quick"; }
  .dashboard-primary, .dashboard-secondary { display: contents; }
  .workspace-resources { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; padding: 0; }
  .workspace-resources a { flex-wrap: wrap; padding: 0 12px 0 0; border-bottom: 0; border-right: 1px solid var(--yx-line); }
  .workspace-resources a:last-child { border-right: 0; }
  .workspace-resources a > span { flex-basis: 100%; }
  .workspace-resources strong { flex: 1; }
}
@media (max-width: 760px) {
  .overview-board { grid-template-columns: minmax(0, 1fr) 40%; gap: 24px 12px; padding: 0; }
  .lunar-welcome { gap: 16px; }
  .lunar-welcome-moon { width: 100%; height: auto; aspect-ratio: 1; }
  .lunar-welcome h2 { max-width: 6em; font-size: 22px; letter-spacing: 0; text-wrap: balance; }
  .lunar-welcome p { font-size: 12px; line-height: 1.8; }
  .dashboard-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .dashboard-stats > :nth-child(2n) { border-right: 0; }
  .dashboard-stats > :nth-child(-n+2) { border-bottom: 1px solid var(--yx-line); }
  .dashboard-stats :deep(.yx-stat) { padding: 18px; }
  .dashboard-stats :deep(.yx-stat-value) { font-size: 26px; }
  .dashboard-stats :deep(.yx-stat-icon) { right: 16px; top: 22px; }
  .dashboard-workspace { grid-template-columns: 1fr; grid-template-areas: "today" "runtime" "resources" "quick" "guide"; gap: 20px; }
  .message-split strong { font-size: 28px; }
  .usage-grid { grid-template-columns: 1fr; gap: 0; }
  .usage-grid > :last-child { padding-left: 0; border-left: 0; }
  .failure-summary { gap: 16px; }
  .quick-grid { grid-template-columns: 1fr; }
  .quick-item:nth-last-child(2) { border-bottom: 1px solid var(--yx-line); }
  .quick-item { min-height: 66px; padding: 13px 2px; }
  .quick-arrow { display: block; }
  .workspace-resources { display: block; }
  .workspace-resources a { flex-wrap: nowrap; padding: 14px 8px; border-right: 0; border-bottom: 1px solid var(--yx-line); }
  .workspace-resources a > span { flex-basis: auto; }
  .workspace-resources strong { flex: none; }
  .system-config { margin-left: 0; }
  .refresh-time { flex-basis: 100%; }
}
</style>
