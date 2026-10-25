<template>
  <div class="yx-page connections-page">
    <PageHeader title="账号与机器人" description="连接个人账号或官方机器人，让对话在月叙汇合。">
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新状态</el-button>
      <el-button type="primary" :icon="Plus" @click="openCreate('wechat_clawbot')">添加连接</el-button>
    </PageHeader>

    <section class="yx-card channel-section" aria-labelledby="channel-title">
      <div class="section-heading"><div><h2 id="channel-title">选择你的接入方式</h2><p>个人账号与机器人，分别配置</p></div><span>{{ CHANNELS.length }} 种接入方式</span></div>
      <div class="channel-grid">
        <button v-for="channel in CHANNELS" :key="channel.value" type="button" class="channel-choice" @click="openCreate(channel.value)">
          <span class="channel-choice-icon"><el-icon><component :is="channel.icon" /></el-icon></span>
          <span class="channel-choice-content"><span class="channel-choice-title"><strong>{{ channel.label }}</strong><span>{{ channel.note }}</span></span><span class="channel-description">{{ channel.description }}</span></span>
          <span class="channel-action"><span>{{ channel.action || (channel.method === 'qr' ? '扫码接入' : '配置接入') }}</span><el-icon><ArrowRight /></el-icon></span>
        </button>
      </div>
    </section>

    <section class="yx-card connections-list" aria-labelledby="connections-title">
      <div class="connections-list-head">
        <div><h2 id="connections-title">已添加的连接 <span>{{ accounts.length }}</span></h2><p>查看连接状态，管理每个账号的对话配置。</p></div>
        <div class="connection-summary"><span><i class="status-dot online" aria-hidden="true"></i><strong>{{ onlineCount }}</strong> 在线</span><span><i class="status-dot" aria-hidden="true"></i><strong>{{ accounts.length - onlineCount }}</strong> 待连接</span></div>
      </div>
      <div class="connections-toolbar">
        <el-radio-group v-model="kindFilter" aria-label="筛选连接类型">
          <el-radio-button value="all">全部</el-radio-button><el-radio-button value="bot">机器人</el-radio-button><el-radio-button value="account">个人账号</el-radio-button>
        </el-radio-group>
        <span class="connection-result-count">共 {{ filteredAccounts.length }} 个连接</span>
      </div>
      <el-table v-loading="loading" :data="filteredAccounts" row-key="id" class="connections-table">
        <el-table-column label="连接名称" min-width="190">
          <template #default="{row}"><div class="connection-name"><span class="connection-icon"><el-icon><component :is="channelInfo(row.platform).icon" /></el-icon></span><div><strong>{{ row.name }}</strong><small>{{ row.account_no || '尚未连接' }}</small></div></div></template>
        </el-table-column>
        <el-table-column label="接入方式" min-width="160"><template #default="{row}"><span class="provider-name">{{ channelInfo(row.platform).label }}</span><div class="muted small">{{ channelInfo(row.platform).kind === 'bot' ? '机器人' : '个人账号' }}</div></template></el-table-column>
        <el-table-column label="连接状态" min-width="170"><template #default="{row}"><el-tag size="small" :type="accountStatusType(row.status)" effect="plain">{{ row.status_label || row.status }}</el-tag><div v-if="row.last_error || row.runtime?.last_error" class="connection-error" :title="row.runtime?.last_error || row.last_error">{{ row.runtime?.last_error || row.last_error }}</div><div v-else class="muted small last-online">{{ row.last_online_at ? formatDateTime(row.last_online_at) : '等待首次连接' }}</div></template></el-table-column>
        <el-table-column label="对话配置" min-width="180"><template #default="{row}"><div class="binding-label">{{ row.character_id ? '独立人设' : '全局默认人设' }}</div><div class="muted small">{{ row.model_id ? '独立模型' : '全局默认模型' }}</div><div class="muted small">记忆库：{{ memoryLibraryName(row) }}</div></template></el-table-column>
        <el-table-column label="自动连接" width="95" align="center"><template #default="{row}"><el-switch v-model="row.auto_connect" :aria-label="`${row.name}自动连接`" :loading="isBusy(row,'auto')" @change="toggleAutoConnect(row)" /></template></el-table-column>
        <el-table-column label="操作" width="220" fixed="right"><template #default="{row}"><div class="connection-ops">
          <el-button v-if="channelInfo(row.platform).method === 'qr' && row.status !== 'online'" link type="primary" :loading="isBusy(row,'qrcode')" @click="openQrcode(row)">扫码登录</el-button>
          <el-button link type="primary" :loading="isBusy(row,'reconnect')" @click="reconnect(row)">{{ row.status === 'online' ? '重新连接' : '连接' }}</el-button>
          <el-button link @click="openEdit(row)">设置</el-button>
          <el-dropdown trigger="click" @command="command => handleRowCommand(row,command)">
            <el-button text circle :aria-label="`${row.name}更多操作`"><el-icon><MoreFilled /></el-icon></el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item v-if="channelInfo(row.platform).contacts" command="groups">拉取群列表</el-dropdown-item>
              <el-dropdown-item v-if="channelInfo(row.platform).contacts" command="friends">拉取好友列表</el-dropdown-item>
              <el-dropdown-item v-if="row.platform === 'qq_bot' && row.adapter_config?.transport === 'webhook'" command="callback">复制事件回调地址</el-dropdown-item>
              <el-dropdown-item command="logout">断开连接</el-dropdown-item>
              <el-dropdown-item command="delete" divided>删除连接</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
        </div></template></el-table-column>
        <template #empty><div class="connections-empty"><span class="connections-empty-mark"><img :src="logo" width="40" height="40" alt="" /></span><strong>{{ accounts.length ? '这个分类里还没有连接' : '点亮你的第一个连接' }}</strong><p>{{ accounts.length ? '切换上方筛选，查看其他已添加的连接。' : '选择上方的接入方式，添加账号或机器人。' }}</p><el-button v-if="!accounts.length" :icon="Plus" @click="openCreate('wechat_clawbot')">添加连接</el-button></div></template>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" :title="editId ? `设置 · ${selectedChannel.label}` : `添加${selectedChannel.label}`" width="650px" :close-on-click-modal="false">
      <el-form ref="accountFormRef" :model="form" :rules="accountRules" label-position="top" @submit.prevent="saveAccount">
        <div class="connection-form-heading"><span class="channel-choice-icon"><el-icon><component :is="selectedChannel.icon" /></el-icon></span><div><strong>连接信息</strong><p>{{ selectedChannel.note }}</p></div></div>
        <div class="form-grid">
          <el-form-item :label="quickLogin ? '连接名称（选填）' : '连接名称'" prop="name"><el-input v-model="form.name" maxlength="64" :placeholder="quickLogin ? selectedChannel.label : '为这个连接起个容易识别的名字'" /></el-form-item>
          <el-form-item label="接入方式" prop="platform"><el-select v-model="form.platform" :disabled="!!editId" @change="applyProfile"><el-option v-for="channel in CHANNELS" :key="channel.value" :label="channel.label" :value="channel.value" /></el-select></el-form-item>
        </div>
        <el-form-item v-if="form.platform === 'qq'" label="登录方式"><el-radio-group v-model="form.managed" :disabled="!!editId" aria-label="QQ 登录方式"><el-radio :value="true">自动配置，只需扫码</el-radio><el-radio :value="false">连接已有 NapCat</el-radio></el-radio-group></el-form-item>
        <div class="yx-hint channel-guide">{{ form.platform === 'qq' && !form.managed ? '请先启动 NapCat，并填写发送消息与扫码所需的连接信息。' : selectedChannel.guide }}</div>
        <template v-if="form.platform === 'qq_bot'">
          <div class="form-grid"><el-form-item label="AppID" prop="app_id"><el-input v-model="form.app_id" placeholder="QQ 开放平台中的 AppID" /></el-form-item><el-form-item label="AppSecret" prop="adapter_token"><el-input v-model="form.adapter_token" type="password" show-password autocomplete="new-password" :placeholder="editId ? '已保存，留空保持不变' : 'QQ 开放平台中的 AppSecret'" /></el-form-item></div>
          <el-form-item label="消息接收方式"><el-radio-group v-model="form.transport"><el-radio value="websocket">长连接（本机可用）</el-radio><el-radio value="webhook">HTTPS 事件回调</el-radio></el-radio-group></el-form-item>
          <div v-if="editId && form.transport === 'webhook'" class="callback-guide"><strong>事件回调地址</strong><p>在 QQ 开放平台中配置可公网访问的 HTTPS 地址，并订阅群聊、单聊事件。</p><div><code>{{ callbackUrl(editId) }}</code><el-button size="small" @click="copyCallback(editId)">复制</el-button></div><small v-if="isLocalPreview">当前是本机地址，QQ 平台无法直接回调；部署 HTTPS 服务后使用相同路径。</small></div>
          <el-form-item v-if="!editId && form.transport === 'webhook'" class="muted small">保存后可在设置中复制事件回调地址。</el-form-item>
        </template>
        <template v-else-if="form.platform === 'wechat' || (form.platform === 'qq' && !form.managed)">
          <el-form-item :label="form.platform === 'qq' ? 'OneBot HTTP 地址' : 'Gewechat API 地址'" prop="adapter_base_url"><el-input v-model="form.adapter_base_url" :placeholder="selectedChannel.baseUrl" /></el-form-item>
          <div class="form-grid" v-if="form.platform === 'qq'">
            <el-form-item label="NapCat WebUI 地址" prop="webui_url"><el-input v-model="form.webui_url" placeholder="http://127.0.0.1:6099" /></el-form-item>
            <el-form-item label="NapCat WebUI Token" prop="webui_token"><el-input v-model="form.webui_token" type="password" show-password autocomplete="new-password" :placeholder="editId && form.has_webui_token ? '已保存，留空保持不变' : 'NapCat 管理面板的 Token'" /></el-form-item>
          </div>
          <div class="form-grid">
            <el-form-item :label="form.platform === 'qq' ? 'OneBot Token（按需）' : 'Gewechat Token（可自动获取）'"><el-input v-model="form.adapter_token" type="password" show-password autocomplete="new-password" :placeholder="editId ? '留空保持原值' : '未启用鉴权时可留空'" /></el-form-item>
            <el-form-item v-if="form.platform === 'wechat'" label="AppID（可自动获取）"><el-input v-model="form.app_id" placeholder="首次扫码可留空" /></el-form-item>
          </div>
          <div v-if="editId && form.platform === 'qq'" class="callback-guide"><strong>接收 QQ 消息</strong><p>在 NapCat 中添加 WebSocket 客户端，将反向连接地址设为：</p><code>{{ onebotWsUrl(editId) }}</code><p>若 NapCat 运行在容器或另一台电脑，请将地址改为它能访问的月叙服务地址。</p></div>
        </template>
        <el-form-item label="绑定记忆库">
          <el-select v-model="form.memory_library_id" filterable :loading="memoryLibrariesLoading" :disabled="memoryLibrariesLoading" aria-label="绑定记忆库">
            <el-option :label="editId ? '使用本连接原有的独立记忆库' : '创建独立记忆库'" value="" />
            <el-option v-for="library in availableMemoryLibraries" :key="library.id" :label="`${library.name} · ${library.memory_count} 条记忆`" :value="library.id" />
          </el-select>
          <p class="muted small">QQ 换号后可选择原来的记忆库，继续读取和写入记忆。切换绑定会保留各库内容；多个连接绑定同一库时会共享记忆。</p>
          <p v-if="memoryLibrariesError" class="connection-error" role="alert">{{ memoryLibrariesError }}<el-button link type="primary" @click="loadMemoryLibraries">重试</el-button></p>
        </el-form-item>
        <el-collapse class="connection-advanced">
          <el-collapse-item title="人设、模型与对话能力" name="dialogue">
            <div class="form-grid">
              <el-form-item label="人设"><el-select v-model="form.character_id" filterable clearable placeholder="跟随全局默认人设"><el-option v-for="item in characters" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
              <el-form-item label="模型"><el-select v-model="form.model_id" filterable clearable placeholder="跟随全局默认模型"><el-option v-for="item in models" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
            </div>
            <div class="switch-grid"><label v-for="item in switchOptions" :key="item.key" class="switch-item"><el-switch v-model="form.settings[item.key]" :disabled="['emoji','voice'].includes(item.key) && !selectedChannel.media" :aria-label="item.label" /><span>{{ item.label }}</span></label></div>
            <p v-if="!selectedChannel.media" class="muted small">当前官方机器人通道发送文本，图片和语音开关暂不可用。</p>
          </el-collapse-item>
        </el-collapse>
        <div v-if="editId || !quickLogin" class="auto-connect-line"><div><strong>自动连接</strong><p>服务启动后恢复连接；手动断开会关闭自动连接。</p></div><el-switch v-model="form.auto_connect" aria-label="自动连接" /></div>
      </el-form>
      <template #footer><el-button @click="dialogVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveAccount">{{ editId ? '保存设置' : quickLogin ? '开始扫码' : '保存连接' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="qrVisible" :title="`${qrAccount ? channelInfo(qrAccount.platform).label : ''} · 扫码登录`" width="440px" :close-on-click-modal="false" @close="stopQrPolling">
      <div class="qr-panel" :aria-busy="qrLoading">
        <p class="qr-account-name">{{ qrAccount?.name }}</p>
        <div v-if="qrStatus === 'preparing'" class="preparation-panel" role="status"><el-icon class="is-loading" :size="36"><Loading /></el-icon><strong>{{ preparationLabel }}</strong><span>首次下载组件或拉取服务器镜像，完成后自动显示二维码。中断可重试，支持时会续传。</span></div>
        <div v-else v-loading="qrLoading" class="qr-canvas"><img v-if="qrImage" :src="qrImage" width="232" height="232" alt="请使用对应手机应用扫描此登录二维码" /><el-icon v-else :size="46"><FullScreen /></el-icon></div>
        <el-tag :type="qrTagType" effect="plain">{{ qrStatusLabel }}</el-tag>
        <p class="qr-message" role="status">{{ qrMessage || '请使用手机扫码，并在手机上确认登录。' }}</p>
        <p v-if="qrCountdown > 0 && qrStatus === 'waiting_qr'" class="qr-countdown">二维码 {{ qrCountdown }} 秒后自动刷新</p>
        <el-alert v-if="qrError" :title="qrError" type="error" :closable="false" show-icon class="qr-error" />
        <form v-if="qrNeedsCode" class="verify-code-form" @submit.prevent="verifyLogin"><label for="clawbot-code">微信手机端显示的验证码</label><div><el-input id="clawbot-code" v-model="verifyCode" inputmode="numeric" maxlength="12" autocomplete="one-time-code" placeholder="输入手机上的验证码" /><el-button native-type="submit" type="primary" :loading="verifying">确认</el-button></div></form>
        <p class="qr-help">{{ qrAccount?.platform === 'wechat_clawbot' ? '请确认手机微信中已启用 ClawBot。' : qrAccount?.adapter_config?.managed ? '扫码并在手机上确认后，将自动恢复连接。' : '扫码依赖已启动的协议服务，请先检查连接设置。' }}</p>
      </div>
      <template #footer><el-button @click="qrVisible=false">关闭</el-button><el-button :icon="Refresh" type="primary" :loading="qrLoading" @click="openQrcode(qrAccount,true)">{{ qrStatus === 'preparing' ? '正在准备' : qrPrepareStage && qrPrepareStage !== 'ready' ? '重新准备' : '刷新二维码' }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="contactsVisible" :title="contactsType === 'groups' ? '群列表' : '好友列表'" size="440px">
      <p class="muted small">{{ contactsAccount?.name }} · 共 {{ contactsItems.length }} 项</p>
      <el-table v-loading="contactsLoading" :data="contactsItems"><el-table-column :prop="contactsType === 'groups' ? 'group_id' : 'user_id'" label="ID" min-width="150" /><el-table-column :prop="contactsType === 'groups' ? 'group_name' : 'nickname'" label="名称" min-width="150" /></el-table>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, FullScreen, Loading, MoreFilled, Plus, Refresh } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import logo from '@/assets/yuexu.svg'
import { createAccount, deleteAccount, fetchFriends, fetchGroups, listAccounts, listMemoryLibraries, logoutAccount, pollAccountPreparation, pollLoginStatus, prepareAccount, reconnectAccount, requestQrcode, submitLoginCode, updateAccount } from '@/api/account'
import { listCharacters } from '@/api/character'
import { listModels } from '@/api/model'
import { accountStatusType, formatDateTime } from '@/utils/format'
import { CHANNELS, channelInfo } from '@/utils/channels'

const accounts = ref([])
const loading = ref(false)
const kindFilter = ref('all')
const onlineCount = computed(() => accounts.value.filter(item => item.status === 'online').length)
const filteredAccounts = computed(() => accounts.value.filter(item => kindFilter.value === 'all' || channelInfo(item.platform).kind === kindFilter.value))
const dialogVisible = ref(false)
const editId = ref('')
const saving = ref(false)
const busyAction = ref('')
const accountFormRef = ref(null)
const characters = ref([])
const models = ref([])
const memoryLibraries = ref([])
const memoryLibrariesLoading = ref(false)
const memoryLibrariesError = ref('')
const switchOptions = [{key:'ai',label:'AI 对话'},{key:'context',label:'上下文'},{key:'memory',label:'长期记忆'},{key:'search',label:'联网搜索'},{key:'vitality',label:'活力搭话'},{key:'emoji',label:'表情'},{key:'voice',label:'语音'}]
function defaultForm(platform='wechat_clawbot') {
  const channel=channelInfo(platform)
  return {name:'',platform,managed:platform==='qq',adapter_base_url:channel.baseUrl || '',adapter_token:'',app_id:'',transport:'websocket',webui_url:'http://127.0.0.1:6099',webui_token:'',has_webui_token:false,character_id:'',model_id:'',memory_library_id:'',auto_connect:platform==='qq_bot',settings:{ai:true,context:true,memory:true,search:true,vitality:true,emoji:!!channel.media,voice:!!channel.media}}
}
const form=reactive(defaultForm())
const selectedChannel=computed(() => channelInfo(form.platform))
const availableMemoryLibraries=computed(() => memoryLibraries.value.filter(library => library.id !== editId.value && (!library.platform || library.platform === form.platform)))
const quickLogin=computed(() => !editId.value && (form.platform==='wechat_clawbot' || (form.platform==='qq' && form.managed)))
const accountRules={
  name:[{validator:(_,value,done) => done(!quickLogin.value && !value.trim() ? Error('请输入连接名称') : undefined),trigger:'blur'}],
  platform:[{required:true,message:'请选择接入方式',trigger:'change'}],
  app_id:[{validator:(_,value,done) => done(form.platform==='qq_bot' && !value.trim() ? Error('请输入 QQ AppID') : undefined),trigger:'blur'}],
  adapter_token:[{validator:(_,value,done) => done(form.platform==='qq_bot' && !editId.value && !value.trim() ? Error('请输入 AppSecret') : undefined),trigger:'blur'}],
  webui_token:[{validator:(_,value,done) => done(form.platform==='qq' && !form.managed && !form.has_webui_token && !value.trim() ? Error('请输入 NapCat WebUI Token') : undefined),trigger:'blur'}],
  webui_url:[{required:true,message:'请输入 NapCat WebUI 地址',trigger:'blur'}],
  adapter_base_url:[{required:true,message:'请输入协议服务地址',trigger:'blur'}],
}
const isLocalPreview=['localhost','127.0.0.1','::1'].includes(window.location.hostname)
const callbackUrl=id => `${window.location.origin}/api/bot/qq/${encodeURIComponent(id)}`
const onebotWsUrl=id => `${window.location.origin.replace(/^http/,'ws')}/api/bot/onebot/ws/${encodeURIComponent(id)}`
async function copyCallback(id) { try { await navigator.clipboard.writeText(callbackUrl(id)); ElMessage.success('回调地址已复制') } catch { ElMessage.warning('复制失败，请在设置中手动复制回调地址') } }
function errorText(error) { const message=error.response?.data?.message; return typeof message==='string' ? message : error.message || '请求失败，请检查连接设置后重试' }
function isBusy(row,action) { return busyAction.value === `${action}:${row.id}` }
async function load() {
  loading.value=true
  try { const [data]=await Promise.all([listAccounts(),loadMemoryLibraries()]); accounts.value=Array.isArray(data)?data:[] } catch { /* 请求拦截器显示错误 */ } finally { loading.value=false }
}
async function loadMemoryLibraries() {
  memoryLibrariesLoading.value=true; memoryLibrariesError.value=''
  try { const data=await listMemoryLibraries(); memoryLibraries.value=Array.isArray(data)?data:[] }
  catch { memoryLibrariesError.value='记忆库列表加载失败，请重试后选择。' }
  finally { memoryLibrariesLoading.value=false }
}
function memoryLibraryName(account) { return memoryLibraries.value.find(library => library.id === (account.memory_library_id || account.id))?.name || (account.memory_library_id && account.memory_library_id !== account.id ? account.memory_library_id : '独立记忆库') }
async function loadBindings() {
  const [people,engines]=await Promise.allSettled([listCharacters({page_size:100}),listModels(),loadMemoryLibraries()])
  if(people.status==='fulfilled') characters.value=people.value.items || people.value || []
  if(engines.status==='fulfilled') models.value=engines.value.items || engines.value || []
}
function applyProfile(platform) {
  const next=defaultForm(platform)
  Object.assign(form,{platform,managed:next.managed,adapter_base_url:next.adapter_base_url,adapter_token:'',app_id:'',webui_token:'',has_webui_token:false,memory_library_id:'',auto_connect:next.auto_connect,settings:{...form.settings,emoji:next.settings.emoji,voice:next.settings.voice}})
  nextTick(() => accountFormRef.value?.clearValidate())
}
function openCreate(platform='wechat_clawbot') { editId.value=''; Object.assign(form,defaultForm(platform)); dialogVisible.value=true; loadBindings(); nextTick(() => accountFormRef.value?.clearValidate()) }
function openEdit(row) {
  editId.value=row.id
  Object.assign(form,defaultForm(row.platform),{name:row.name,managed:row.adapter_config?.managed===true,adapter_base_url:row.adapter_base_url || channelInfo(row.platform).baseUrl,app_id:row.adapter_config?.app_id || '',transport:row.adapter_config?.transport || 'websocket',webui_url:row.adapter_config?.webui_url || 'http://127.0.0.1:6099',has_webui_token:row.has_webui_token,character_id:row.character_id || '',model_id:row.model_id || '',memory_library_id:row.memory_library_id && row.memory_library_id !== row.id ? row.memory_library_id : '',auto_connect:!!row.auto_connect,settings:{...defaultForm(row.platform).settings,...row.settings}})
  dialogVisible.value=true; loadBindings(); nextTick(() => accountFormRef.value?.clearValidate())
}
async function saveAccount() {
  if(saving.value) return
  try { await accountFormRef.value.validate() } catch { return }
  saving.value=true
  try {
    const managed=form.platform==='qq' && form.managed
    const startLogin=quickLogin.value
    const adapterConfig={}
    if(form.platform==='qq_bot') adapterConfig.transport=form.transport
    if(['qq_bot','wechat'].includes(form.platform)) adapterConfig.app_id=form.app_id.trim()
    if(form.platform==='qq') { adapterConfig.managed=form.managed; if(!managed) { adapterConfig.webui_url=form.webui_url.trim(); if(form.webui_token.trim()) adapterConfig.webui_token=form.webui_token.trim() } }
    const settings={...form.settings}
    if(!selectedChannel.value.media) { settings.emoji=false; settings.voice=false }
    const payload={name:form.name.trim(),platform:form.platform,adapter_config:adapterConfig,character_id:form.character_id || '',model_id:form.model_id || '',memory_library_id:form.memory_library_id,auto_connect:form.auto_connect,settings}
    if(!managed || !editId.value) payload.adapter_base_url=managed?'':form.adapter_base_url.trim()
    if(form.adapter_token.trim() && !managed) payload.adapter_token=form.adapter_token.trim()
    const saved=editId.value ? await updateAccount(editId.value,payload) : await createAccount(payload)
    dialogVisible.value=false; ElMessage.success('连接设置已保存'); await load()
    if(startLogin) await openQrcode(saved)
  } catch { /* 请求拦截器显示错误 */ } finally { saving.value=false }
}
async function toggleAutoConnect(row) {
  busyAction.value=`auto:${row.id}`
  try { await updateAccount(row.id,{auto_connect:row.auto_connect}) } catch { row.auto_connect=!row.auto_connect } finally { busyAction.value='' }
}

const qrVisible=ref(false)
const qrLoading=ref(false)
const qrData=ref(null)
const qrAccount=ref(null)
const qrStatus=ref('waiting_qr')
const qrPrepareStage=ref('')
const qrMessage=ref('')
const qrError=ref('')
const qrNeedsCode=ref(false)
const verifyCode=ref('')
const verifying=ref(false)
let qrTimer=null
let qrGeneration=0
let qrCountdownTimer=null
const qrCountdown=ref(0)
const qrImage=computed(() => { const data=qrData.value; if(!data) return ''; if(data.image_base64) return data.image_base64.startsWith('data:')?data.image_base64:`data:image/png;base64,${data.image_base64}`; return data.image_url || '' })
const preparationLabel=computed(() => ({checking:'检查登录环境',downloading:'下载或恢复登录组件',configuring:'自动配置连接',starting:'启动登录服务',stopping:'正在停止旧登录服务'}[qrPrepareStage.value] || '准备登录环境'))
const qrStatusLabel=computed(() => ({preparing:'正在准备',waiting_qr:'等待扫码',scanning:'等待手机确认',online:'连接成功',error:'需要重试',offline:'连接已断开'}[qrStatus.value] || '等待扫码'))
const qrTagType=computed(() => qrStatus.value==='online'?'success':qrStatus.value==='error'?'danger':'info')
function stopQrPolling() { qrGeneration++; if(qrTimer) window.clearTimeout(qrTimer); qrTimer=null; stopQrCountdown(); qrLoading.value=false; if(busyAction.value.startsWith('qrcode:')) busyAction.value='' }
function stopQrCountdown() { if(qrCountdownTimer) window.clearInterval(qrCountdownTimer); qrCountdownTimer=null; qrCountdown.value=0 }
function scheduleQrCountdown(id,generation,seconds) {
  stopQrCountdown()
  const deadline=Date.now()+seconds*1000
  qrCountdown.value=seconds
  qrCountdownTimer=window.setInterval(async () => {
    if(generation!==qrGeneration || !qrVisible.value) { stopQrCountdown(); return }
    const left=Math.max(0,Math.ceil((deadline-Date.now())/1000))
    qrCountdown.value=left
    if(left>0) return
    stopQrCountdown()
    // 仅等待扫码阶段自动刷新；已扫码后刷新会使确认失效。
    if(qrStatus.value!=='waiting_qr' || qrLoading.value) return
    try {
      const data=await requestQrcode(id,true)
      if(generation!==qrGeneration || !qrVisible.value) return
      qrData.value=data; qrMessage.value='二维码已自动刷新，请重新扫码。'; load()
      scheduleQrCountdown(id,generation,data.expires_in||120)
    } catch(error) { showQrError(error,generation) }
  },1000)
}
async function openQrcode(row,refresh=false) {
  if(!row) return
  stopQrPolling(); const generation=qrGeneration
  const managed=row.platform==='qq' && row.adapter_config?.managed===true
  qrAccount.value=row; qrData.value=null; qrError.value=''; qrMessage.value='正在获取登录二维码'; qrNeedsCode.value=false; verifyCode.value=''; qrStatus.value='waiting_qr'; qrVisible.value=true; qrLoading.value=true; busyAction.value=`qrcode:${row.id}`
  qrPrepareStage.value=managed?'checking':''
  if(managed) { qrStatus.value='preparing'; qrMessage.value='正在检查登录环境' }
  try {
    if(managed) await applyPreparation(await prepareAccount(row.id),row,generation,refresh)
    else await fetchQrcode(row,generation,refresh)
  } catch(error) { showQrError(error,generation) }
}
function showQrError(error,generation) {
  if(generation!==qrGeneration || !qrVisible.value) return
  qrError.value=errorText(error); qrStatus.value='error'; qrMessage.value=qrPrepareStage.value && qrPrepareStage.value!=='ready' ? '准备未完成，处理上方问题后点击重新准备。' : '请重新获取二维码；若仍失败，请检查连接设置。'; qrLoading.value=false; busyAction.value=''
}
async function applyPreparation(data,row,generation,refresh) {
  if(generation!==qrGeneration || !qrVisible.value) return
  qrPrepareStage.value=data.stage || 'checking'
  qrMessage.value=data.message || preparationLabel.value
  if(data.status==='error') throw Error(data.message || '登录环境准备失败，请重试')
  if(data.status==='ready') {
    qrPrepareStage.value='ready'
    const login=await pollLoginStatus(row.id)
    if(generation!==qrGeneration || !qrVisible.value) return
    if(login.status==='online' || (login.status==='scanning' && !refresh)) {
      qrLoading.value=false; busyAction.value=''
      if(applyLoginState(login,generation)) schedulePoll(row.id,generation)
      return
    }
    await fetchQrcode(row,generation,refresh); return
  }
  if(!['preparing','idle'].includes(data.status)) throw Error('登录环境状态异常，请重新准备')
  qrTimer=window.setTimeout(async () => {
    if(generation!==qrGeneration || !qrVisible.value) return
    try { await applyPreparation(await (data.status==='idle' ? prepareAccount(row.id) : pollAccountPreparation(row.id)),row,generation,refresh) }
    catch(error) { showQrError(error,generation) }
  },1500)
}
async function fetchQrcode(row,generation,refresh) {
  qrStatus.value='waiting_qr'; qrMessage.value='正在获取登录二维码'
  const data=await requestQrcode(row.id,refresh)
  if(generation!==qrGeneration || !qrVisible.value) return
  qrData.value=data; qrMessage.value='请使用手机扫码，并在手机上确认登录。'; qrLoading.value=false; busyAction.value=''; schedulePoll(row.id,generation); scheduleQrCountdown(row.id,generation,data.expires_in||120); load()
}
function applyLoginState(data,generation) {
  if(generation!==qrGeneration || !qrVisible.value) return false
  qrStatus.value=data.status; qrMessage.value=data.message || ''; qrNeedsCode.value=!!data.needs_verify_code; qrError.value=''
  if(data.status!=='waiting_qr') stopQrCountdown()
  if(data.status==='online') { stopQrPolling(); qrVisible.value=false; ElMessage.success('连接成功'); load(); return false }
  if(data.status==='error' || data.status==='offline') { qrError.value=data.message || '请刷新二维码后重试'; return false }
  return !qrNeedsCode.value
}
function schedulePoll(id,generation) {
  qrTimer=window.setTimeout(async () => {
    if(generation!==qrGeneration || !qrVisible.value) return
    let again=true
    try {
      const data=await pollLoginStatus(id)
      again=applyLoginState(data,generation)
      if(again && data.status==='waiting_qr' && !qrImage.value) {
        await fetchQrcode(qrAccount.value,generation,false)
        return
      }
    }
    catch(error) { if(generation===qrGeneration) qrError.value=errorText(error) }
    if(again && generation===qrGeneration && qrVisible.value) schedulePoll(id,generation)
  },2500)
}
async function verifyLogin() {
  if(verifying.value || !/^\d{4,12}$/.test(verifyCode.value)) { ElMessage.warning('请输入手机端显示的数字验证码'); return }
  const generation=qrGeneration; verifying.value=true
  try { if(applyLoginState(await submitLoginCode(qrAccount.value.id,verifyCode.value),generation)) schedulePoll(qrAccount.value.id,generation) }
  catch(error) { if(generation===qrGeneration) qrError.value=errorText(error) } finally { verifying.value=false }
}
async function reconnect(row) {
  busyAction.value=`reconnect:${row.id}`
  try { const data=await reconnectAccount(row.id); if(data.preparing || data.needs_qrcode) { await openQrcode(row); return }; if(data.success===false) ElMessage.warning(data.error || '连接失败，请检查设置'); else ElMessage.success('连接成功'); await load() } catch { /* 请求拦截器显示错误 */ } finally { if(busyAction.value===`reconnect:${row.id}`) busyAction.value='' }
}
async function logout(row) { try { await logoutAccount(row.id); ElMessage.success('已断开连接并关闭自动连接'); await load() } catch { /* 请求拦截器显示错误 */ } }
async function removeAccount(row) {
  try { await ElMessageBox.confirm(`确定删除连接「${row.name}」吗？记忆库会保留，新连接仍可绑定；连接信息需要重新配置。`,'删除连接',{type:'warning',confirmButtonText:'删除',cancelButtonText:'取消'}) } catch { return }
  try { await deleteAccount(row.id); ElMessage.success('连接已删除'); await load() } catch { /* 请求拦截器显示错误 */ }
}
function handleRowCommand(row,command) { if(command==='delete') removeAccount(row); else if(command==='logout') logout(row); else if(command==='callback') copyCallback(row.id); else openContacts(row,command) }
const contactsVisible=ref(false)
const contactsType=ref('groups')
const contactsLoading=ref(false)
const contactsItems=ref([])
const contactsAccount=ref(null)
async function openContacts(row,type) {
  contactsAccount.value=row; contactsType.value=type; contactsItems.value=[]; contactsVisible.value=true; contactsLoading.value=true
  try { const data=await (type==='groups'?fetchGroups(row.id):fetchFriends(row.id)); contactsItems.value=Array.isArray(data)?data:[] } catch { /* 请求拦截器显示错误 */ } finally { contactsLoading.value=false }
}
onMounted(load)
onBeforeUnmount(() => { qrVisible.value=false; stopQrPolling() })
</script>

<style scoped>
.channel-section { padding:20px 24px 24px; }
.section-heading { display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px; }
.section-heading > div { display:flex;align-items:baseline;gap:16px;flex-wrap:wrap; }
.section-heading h2 { margin:0;font-size:15px;font-weight:600; }
.section-heading p { margin:0;font-size:12px;color:var(--yx-muted); }
.section-heading > span { font-size:12px;color:var(--yx-muted); }
.channel-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px; }
.channel-choice { display:flex;align-items:center;gap:12px;min-width:0;padding:14px 16px;text-align:left;border:1px solid var(--yx-line);border-radius:8px;background:transparent;color:var(--yx-text);font:inherit;cursor:pointer;transition:border-color .18s,background-color .18s; }
.channel-choice:hover { border-color:var(--yx-accent);background:var(--yx-elevated); }
.channel-choice:focus-visible { outline:2px solid var(--yx-accent);outline-offset:3px; }
.channel-choice-icon { display:grid;place-items:center;width:36px;height:36px;flex:none;border:1px solid var(--yx-line);border-radius:9px;background:var(--yx-elevated);color:var(--yx-accent);font-size:19px; }
.channel-choice-content { display:block;flex:1;min-width:0; }
.channel-choice-title { display:flex;align-items:center;gap:9px;flex-wrap:wrap; }
.channel-choice-title strong { font-size:13px;font-weight:500; }
.channel-choice-title > span { color:var(--yx-muted);font-size:11px; }
.channel-description { display:block;margin-top:7px;color:var(--yx-muted);font-size:12px;line-height:1.75;overflow-wrap:anywhere; }
.channel-action { display:flex;align-items:center;gap:9px;flex:none;font-size:12px;color:var(--yx-accent); }
.connections-list { padding:0;overflow:hidden; }
.connections-list-head { display:flex;align-items:center;justify-content:space-between;gap:20px;padding:24px; }
.connections-list-head h2 { display:flex;align-items:center;gap:10px;margin:0;font-size:15px;font-weight:600; }
.connections-list-head h2 > span { display:grid;place-items:center;min-width:24px;height:22px;padding:0 6px;border:1px solid var(--yx-line);border-radius:6px;color:var(--yx-text-2);font-size:11px;font-weight:400;font-variant-numeric:tabular-nums; }
.connections-list-head p { margin:9px 0 0;font-size:12px;line-height:1.65;color:var(--yx-muted); }
.connection-summary { display:flex;align-items:center;gap:24px;flex:none;font-size:12px;color:var(--yx-muted); }
.connection-summary > span { display:flex;align-items:center;gap:7px; }
.connection-summary strong { font-weight:500;font-variant-numeric:tabular-nums;color:var(--yx-text); }
.status-dot { width:6px;height:6px;flex:none;border-radius:50%;background:var(--yx-muted); }
.status-dot.online { background:var(--el-color-success); }
.connections-toolbar { display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 24px;border-top:1px solid var(--yx-line);border-bottom:1px solid var(--yx-line); }
.connection-result-count { font-size:12px;color:var(--yx-muted);font-variant-numeric:tabular-nums; }
.connections-table :deep(.el-table__cell:first-child .cell) { padding-left:24px; }
.connections-table :deep(.el-table__cell:last-child .cell) { padding-right:24px; }
.connections-table :deep(.el-table__inner-wrapper::before) { display:none; }
.connections-table :deep(.el-table__empty-block) { width:100% !important;min-width:0; }
.connection-name { display:flex;align-items:center;gap:12px; }
.connection-name > div { min-width:0; }
.connection-icon { width:34px;height:34px;display:grid;place-items:center;flex:none;border:1px solid var(--yx-line);border-radius:10px;color:var(--yx-accent); }
.connection-name strong { display:block;font-size:13px;font-weight:500;overflow-wrap:anywhere; }
.connection-name small { display:block;color:var(--yx-muted);font-size:12px;margin-top:4px;max-width:180px;overflow:hidden;text-overflow:ellipsis; }
.provider-name { display:block;font-size:12px;margin-bottom:6px; }
.binding-label { margin-bottom:6px;font-size:12px; }
.connection-error { margin-top:8px;font-size:12px;line-height:1.6;color:var(--el-color-danger);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden; }
.last-online { margin-top:7px; }
.connection-ops { display:flex;align-items:center;gap:12px;flex-wrap:wrap; }
.connections-empty { width:100%;padding:40px 20px 44px;display:flex;flex-direction:column;align-items:center;gap:12px;line-height:1.6; }
.connections-empty-mark { display:grid;place-items:center;width:64px;height:64px;border:1px solid var(--yx-line);border-radius:16px;background:var(--yx-elevated);margin-bottom:4px; }
.connections-empty strong { color:var(--yx-text);font-size:14px;font-weight:500; }
.connections-empty p { margin:0 0 6px;font-size:12px;color:var(--yx-muted);line-height:1.8; }
.connection-form-heading { display:flex;align-items:center;gap:12px;padding-bottom:18px;margin-bottom:22px;border-bottom:1px solid var(--yx-line); }
.connection-form-heading strong { font-size:13px;font-weight:500;color:var(--yx-text); }
.connection-form-heading p { margin:5px 0 0;font-size:12px;color:var(--yx-muted); }
.form-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 18px; }
.form-grid .el-select { width:100%; }
.channel-guide { margin-bottom:22px; }
.connection-advanced { margin-top:6px; }
.switch-grid { display:grid;grid-template-columns:repeat(3,1fr);gap:16px 20px;margin:8px 0 18px; }
.switch-item { display:flex;align-items:center;gap:10px;font-size:12px; }
.auto-connect-line { display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:24px;padding-top:20px;border-top:1px solid var(--yx-line); }
.auto-connect-line strong { font-size:12px;font-weight:500; }
.auto-connect-line p { font-size:11px;color:var(--yx-muted);margin:8px 0 0;line-height:1.8; }
.callback-guide { padding:16px;margin-bottom:22px;background:var(--yx-elevated);border-radius:10px; }
.callback-guide strong { font-size:12px; }
.callback-guide p,.callback-guide small { font-size:11px;line-height:1.8;color:var(--yx-muted); }
.callback-guide > div { display:flex;align-items:center;gap:10px; }
.callback-guide code { font-size:11px;overflow-wrap:anywhere;flex:1; }
.callback-guide small { display:block;margin-top:12px; }
.qr-panel { text-align:center; }
.qr-account-name { font-size:13px;color:var(--yx-text-2);margin:8px 0 20px; }
.preparation-panel { display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;min-height:240px;margin-bottom:24px;padding:24px;background:var(--yx-elevated);border-radius:12px;color:var(--yx-accent); }
.preparation-panel strong { font-size:15px;font-weight:500; }
.preparation-panel span { max-width:260px;font-size:12px;line-height:1.8;color:var(--yx-text-2); }
.qr-canvas { display:grid;place-items:center;margin:0 auto 24px;width:264px;aspect-ratio:1;max-width:100%;background:#fff;color:#637085;border:10px solid #fff;border-radius:12px; }
.qr-canvas img { max-width:100%;max-height:100%;object-fit:contain; }
.qr-message { font-size:13px;line-height:1.8;color:var(--yx-text-2); }
.qr-countdown { margin:8px 0 0;font-size:11px;color:var(--yx-muted); }
.qr-error { text-align:left;margin:18px 0; }
.qr-help { font-size:11px;line-height:1.8;color:var(--yx-muted);margin-top:22px; }
.verify-code-form { text-align:left;margin-top:20px; }
.verify-code-form label { font-size:12px; }
.verify-code-form > div { display:flex;align-items:center;gap:10px;margin-top:10px; }
@media (max-width:1200px) {
  .channel-action { flex-direction:column;align-items:flex-end;gap:7px;max-width:70px;text-align:right;font-size:11px;line-height:1.5; }
  .channel-choice-title { gap:5px 9px; }
}
@media (max-width:760px) {
  .channel-section { padding:18px; }
  .section-heading { margin-bottom:15px; }
  .section-heading > div { gap:7px 16px; }
  .section-heading > span { display:none; }
  .channel-grid { grid-template-columns:1fr;gap:8px; }
  .channel-choice { padding:14px 12px;gap:11px; }
  .channel-choice-icon { width:32px;height:32px;font-size:17px; }
  .channel-choice-title { gap:5px 8px; }
  .channel-choice-title strong { font-size:13px; }
  .channel-description { font-size:12px;margin-top:5px; }
  .connections-list-head { align-items:flex-start;flex-direction:column;gap:16px;padding:20px 18px; }
  .connection-summary { gap:24px; }
  .connections-toolbar { padding:12px 18px;gap:10px;flex-wrap:wrap; }
  .connections-toolbar :deep(.el-radio-button__inner) { min-height:36px;display:flex;align-items:center;padding:8px 12px; }
  .connections-table :deep(.el-table-fixed-column--right) { position:static !important; }
  .connections-table :deep(.el-table-fixed-column--right::before) { display:none; }
  .connections-table :deep(.el-table__cell:first-child .cell) { padding-left:18px; }
  .connections-table :deep(.el-table__cell:last-child .cell) { padding-right:18px; }
  .form-grid { grid-template-columns:1fr; }
  .switch-grid { grid-template-columns:repeat(2,1fr); }
  .callback-guide > div { align-items:flex-start;flex-direction:column; }
  .auto-connect-line { align-items:flex-start; }
  .auto-connect-line > .el-switch { flex:none; }
  .verify-code-form > div { align-items:stretch; }
}
@media (max-width:400px) {
  .channel-choice { display:grid;grid-template-columns:32px minmax(0,1fr);gap:8px 11px; }
  .channel-choice-icon { align-self:start; }
  .channel-action { grid-column:2;flex-direction:row;justify-content:space-between;align-items:center;max-width:none;font-size:12px; }
  .switch-grid { gap:12px; }
}
@media (prefers-reduced-motion:reduce) { .preparation-panel .is-loading { animation:none; } }
</style>
