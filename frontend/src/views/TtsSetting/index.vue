<template>
  <div class="yx-page">
    <PageHeader title="TTS 语音" description="支持 Edge-TTS、OpenAI 兼容与 MiniMax 语音模型">
      <el-button :icon="Refresh" :loading="loading" :disabled="saving || synthesizing" @click="loadAll">刷新</el-button>
    </PageHeader>

    <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />

    <el-alert
      v-if="settings && form.engine === settings.engine && !available"
      title="当前语音服务不可用，机器人将降级为文字回复"
      type="warning"
      show-icon
      :closable="false"
    >
      <template v-if="form.engine === 'edge'">
        请执行 <code>pip install -r requirements-optional.txt</code> 安装 Edge-TTS 可选依赖，然后重启服务。
      </template>
      <template v-else>请检查云端接口地址、API Key 与模型名称，保存后重试。</template>
    </el-alert>

    <div class="settings-layout">
      <section class="yx-card settings-main" aria-labelledby="tts-config-title">
        <div class="yx-card-title">
          <h3 id="tts-config-title">语音参数</h3>
          <el-tag size="small" :type="form.enabled ? 'success' : 'info'" effect="plain">
            {{ form.enabled ? '已启用' : '已停用' }}
          </el-tag>
        </div>

        <div v-loading="loading">
          <el-form :model="form" label-position="top" :disabled="saving || synthesizing">
            <section class="form-section" aria-labelledby="tts-service-title">
              <div class="section-heading">
                <h4 id="tts-service-title">语音服务</h4>
                <p>选择合成引擎，并配置对应的声音。</p>
              </div>
              <div class="form-grid">
            <el-form-item label="启用语音">
              <el-switch v-model="form.enabled" aria-label="启用语音" />
            </el-form-item>

            <el-form-item label="语音引擎">
              <el-select v-model="form.engine" style="width: 100%" @change="onEngineChange">
                <el-option label="Edge-TTS" value="edge" />
                <el-option label="云端语音（OpenAI 兼容）" value="openai" />
                <el-option label="MiniMax 语音" value="minimax" />
              </el-select>
            </el-form-item>

            <template v-if="form.engine !== 'edge'">
              <el-form-item label="接口地址 base_url" class="span-2">
                <div class="field-block">
                  <el-input v-model="form.base_url" :placeholder="isMinimax ? 'https://api.minimax.cn/v1' : 'https://api.openai.com/v1'" />
                  <div v-if="isMinimax" class="muted small field-tip">可填写 API 根地址或完整的 /v1/t2a_v2 地址。</div>
                </div>
              </el-form-item>
              <el-form-item label="API Key" class="span-2">
                <div class="field-block">
                  <el-input v-model="form.api_key" type="password" show-password autocomplete="off" />
                  <div class="muted small field-tip">保持掩码保留密钥，清空则删除。更换服务地址后请重新填写 API Key。</div>
                </div>
              </el-form-item>
              <el-form-item label="语音模型">
                <el-input v-model="form.model" :placeholder="isMinimax ? '例如 speech-2.8-hd 或 speech-2.8-turbo' : '填写服务商提供的模型 ID，例如 tts-1'" />
              </el-form-item>
              <el-form-item :label="isMinimax ? 'MiniMax 音色 voice_id' : '云端音色'">
                <el-select v-model="form.cloud_voice" filterable allow-create default-first-option style="width: 100%" placeholder="选择或填写服务商支持的音色 ID">
                  <el-option v-for="voice in voiceOptions" :key="voice.value" :label="voice.label" :value="voice.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="语速倍率">
                <el-input-number v-model="form.speed" :min="isMinimax ? 0.5 : 0.25" :max="isMinimax ? 2 : 4" :step="0.25" controls-position="right" />
              </el-form-item>
              <el-form-item label="请求超时（秒）">
                <el-input-number v-model="form.timeout" :min="1" :max="300" controls-position="right" />
              </el-form-item>
            </template>

            <template v-else>
            <el-form-item label="音色" class="span-2">
              <el-select v-model="form.voice" placeholder="选择音色" style="width: 100%">
                <el-option
                  v-for="voice in voiceOptions"
                  :key="voice.value"
                  :label="voice.label"
                  :value="voice.value"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="语速">
              <div class="field-block">
                <el-input v-model="form.rate" placeholder="+0%" />
                <div class="muted small field-tip">百分比格式，例如 +10% 表示加快 10%</div>
              </div>
            </el-form-item>

            <el-form-item label="音量">
              <div class="field-block">
                <el-input v-model="form.volume" placeholder="+0%" />
                <div class="muted small field-tip">百分比格式，例如 -10% 表示降低音量</div>
              </div>
            </el-form-item>
            </template>
              </div>
            </section>

            <section class="form-section" aria-labelledby="tts-policy-title">
              <div class="section-heading">
                <h4 id="tts-policy-title">发送与缓存</h4>
                <p>自动判断会参考聊天意图与回复内容，选择语音或文字。</p>
              </div>
              <div class="form-grid">
            <el-form-item label="触发策略" class="span-2">
              <el-select v-model="form.trigger" style="width: 100%">
                <el-option label="自动判断（推荐）" value="auto" />
                <el-option label="关闭（不发送语音）" value="never" />
                <el-option label="仅 @ 或私聊" value="at_only" />
                <el-option label="全部消息" value="always" />
              </el-select>
              <div class="muted small field-tip">自动模式：短句陪伴倾向语音；不方便听、代码、链接或长回复保留文字。</div>
            </el-form-item>

            <el-form-item label="最大字数">
              <div class="field-block">
                <el-input-number
                  v-model="form.max_chars"
                  :min="1"
                  :max="1000"
                  :step="10"
                  controls-position="right"
                />
                <div class="muted small field-tip">超过上限会发送完整文字，避免语音说到一半。</div>
              </div>
            </el-form-item>

            <el-form-item label="缓存有效期">
              <div class="field-block">
                <el-input-number
                  v-model="form.cache_ttl_hours"
                  :min="0"
                  :max="720"
                  controls-position="right"
                />
                <div class="muted small field-tip">单位小时，0 表示不自动清理</div>
              </div>
            </el-form-item>
              </div>
            </section>
          </el-form>

          <div class="form-actions">
            <span class="muted small">修改后需保存生效</span>
            <el-button type="primary" :loading="saving" :disabled="loading || !!loadError || synthesizing" @click="saveSettings()">保存设置</el-button>
          </div>
        </div>
      </section>

      <div class="settings-aside">
      <div class="yx-card settings-preview">
        <div class="yx-card-title">
          <h3>试听</h3>
        </div>
        <p class="panel-description">先保存当前设置，再调用选中的语音服务。</p>

        <el-input
          v-model="preview.text"
          type="textarea"
          :rows="3"
          :maxlength="form.max_chars || 200"
          show-word-limit
          placeholder="输入要试听的文本，例如：今晚的月色真美。"
          aria-label="试听文本"
        />

        <div class="yx-toolbar preview-toolbar">
          <el-button
            type="primary"
            :icon="VideoPlay"
            :loading="synthesizing"
            :disabled="loading || saving || !!loadError || !preview.text.trim()"
            @click="onSynthesize"
          >
            保存并生成语音
          </el-button>
          <span class="muted small">生成结果会缓存到语音缓存目录</span>
        </div>

        <p class="muted small">试听与机器人发送的语音均由 AI 合成；使用云端服务时，文本会发送至所配置的服务商，可能产生调用费用。</p>

        <el-alert
          v-if="preview.error"
          :title="preview.error"
          type="error"
          show-icon
          :closable="false"
        />

        <div v-if="preview.result" class="preview-result">
          <audio
            v-if="preview.result.url"
            :src="preview.result.url"
            controls
            class="tts-audio"
          ></audio>
          <div v-else class="mono small file-path">
            文件路径：{{ preview.result.file_path || '—' }}
          </div>
        </div>

        <div v-else-if="!preview.error" class="preview-empty">
          <el-icon :size="24" aria-hidden="true"><VideoPlay /></el-icon>
          <strong>等待语音生成</strong>
          <span>输入一段文本，生成后可在这里播放试听。</span>
        </div>
      </div>

        <div class="yx-card cache-panel">
          <div class="yx-card-title">
            <h3>缓存状态</h3>
            <el-tag size="small" :type="available ? 'success' : 'warning'" effect="plain">
              {{ available ? '语音服务可用' : '语音服务不可用' }}
            </el-tag>
          </div>

          <div v-loading="cacheLoading">
            <el-descriptions :column="1" :label-width="88" border size="small">
              <el-descriptions-item label="缓存文件">
                {{ cache ? `${cache.count ?? 0} 个` : '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="占用空间">
                {{ cache ? formatBytes(cache.size) : '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="缓存目录">
                <span class="mono cache-dir">{{ cache?.dir || '—' }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="服务状态">
                <el-tag size="small" :type="available ? 'success' : 'warning'" effect="plain">
                  {{ available ? '可用' : '不可用' }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>

            <el-empty
              v-if="cache && !cache.count"
              description="暂无语音缓存"
              :image-size="60"
            />

            <div class="cache-actions">
              <el-button :loading="cleaning" :disabled="!cache?.count" @click="onCleanup">
                清理过期
              </el-button>
              <el-button
                type="danger"
                plain
                :loading="clearing"
                :disabled="!cache?.count"
                @click="onClear"
              >
                清空全部
              </el-button>
            </div>

            <div class="yx-hint">
              清理操作不可恢复，语音会在下次需要时自动重新合成并写入缓存。
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, VideoPlay } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import {
  cleanupTtsCache,
  clearTtsCache,
  getTtsCache,
  getTtsSettings,
  listVoices,
  synthesize,
  updateTtsSettings,
} from '@/api/tts'
import { formatBytes } from '@/utils/format'

const settings = ref(null)
const voices = ref([])
const cache = ref(null)
const loading = ref(false)
const loadError = ref('')
const cacheLoading = ref(false)
const saving = ref(false)
const cleaning = ref(false)
const clearing = ref(false)
const synthesizing = ref(false)

const form = reactive({
  enabled: true,
  engine: 'edge',
  base_url: 'https://api.openai.com/v1',
  api_key: '',
  model: '',
  cloud_voice: 'alloy',
  speed: 1,
  timeout: 30,
  voice: 'zh-CN-XiaoxiaoNeural',
  rate: '+0%',
  volume: '+0%',
  trigger: 'auto',
  max_chars: 200,
  cache_ttl_hours: 24,
})

const preview = reactive({ text: '', result: null, error: '' })

const available = computed(
  () => settings.value?.available ?? cache.value?.available ?? true,
)
const isMinimax = computed(() => form.engine === 'minimax')

const voiceOptions = computed(() => {
  const list = form.engine === settings.value?.engine ? voices.value.map((item) => ({ ...item })) : []
  const value = form.engine === 'edge' ? form.voice : form.cloud_voice
  if (value && !list.some((item) => item.value === value)) {
    list.push({ value, label: `${value}（当前）` })
  }
  return list
})

function applySettings(data) {
  settings.value = data
  form.enabled = Boolean(data.enabled)
  form.engine = data.engine || 'edge'
  form.base_url = data.base_url ?? (isMinimax.value ? 'https://api.minimax.cn/v1' : 'https://api.openai.com/v1')
  form.api_key = data.api_key ?? ''
  form.model = data.model ?? ''
  form.cloud_voice = data.cloud_voice || (isMinimax.value ? 'Chinese (Mandarin)_Warm_Bestie' : 'alloy')
  form.speed = data.speed ?? 1
  form.timeout = data.timeout ?? 30
  form.voice = data.voice || 'zh-CN-XiaoxiaoNeural'
  form.rate = data.rate || '+0%'
  form.volume = data.volume || '+0%'
  form.trigger = data.trigger || 'auto'
  form.max_chars = data.max_chars ?? 200
  form.cache_ttl_hours = data.cache_ttl_hours ?? 24
}

function onEngineChange(engine) {
  if (engine === 'edge') return
  const saved = settings.value?.engine === engine ? settings.value : null
  form.base_url = saved?.base_url ?? (engine === 'minimax' ? 'https://api.minimax.cn/v1' : 'https://api.openai.com/v1')
  form.api_key = saved?.api_key ?? ''
  form.model = saved?.model ?? (engine === 'minimax' ? 'speech-2.8-hd' : 'tts-1')
  form.cloud_voice = saved?.cloud_voice || (engine === 'minimax' ? 'Chinese (Mandarin)_Warm_Bestie' : 'alloy')
  form.speed = saved?.speed ?? 1
}

async function loadSettings() {
  loadError.value = ''
  try {
    applySettings(await getTtsSettings())
  } catch {
    loadError.value = '语音配置读取失败，请点击刷新后重试'
  }
}

async function loadVoices() {
  try {
    const data = await listVoices()
    voices.value = Array.isArray(data) ? data : []
  } catch {
    voices.value = []
  }
}

async function loadCache() {
  try {
    cache.value = await getTtsCache()
  } catch {
    cache.value = null
  }
}

async function loadAll() {
  loading.value = true
  cacheLoading.value = true
  try {
    await Promise.all([loadSettings(), loadVoices(), loadCache()])
  } finally {
    loading.value = false
    cacheLoading.value = false
  }
}

async function saveSettings(notify = true) {
  if (saving.value || loadError.value) return false
  saving.value = true
  try {
    const data = await updateTtsSettings({
      enabled: form.enabled,
      engine: form.engine,
      base_url: form.base_url.trim(),
      api_key: form.base_url.trim() !== settings.value?.base_url && /^\*+$/.test(form.api_key) ? '' : form.api_key,
      model: form.model.trim(),
      cloud_voice: form.cloud_voice.trim(),
      speed: form.speed ?? 1,
      timeout: form.timeout ?? 30,
      voice: form.voice,
      rate: form.rate.trim() || '+0%',
      volume: form.volume.trim() || '+0%',
      trigger: form.trigger,
      max_chars: Math.max(1, form.max_chars || 200),
      cache_ttl_hours: Math.max(0, form.cache_ttl_hours ?? 24),
    })
    applySettings(data.tts)
    if (notify) ElMessage.success('语音参数已保存')
    await loadVoices()
    return true
  } catch {
    // 错误提示由请求拦截器统一处理
    return false
  } finally {
    saving.value = false
  }
}

async function onCleanup() {
  try {
    await ElMessageBox.confirm(
      `将清理超过 ${settings.value?.cache_ttl_hours ?? form.cache_ttl_hours ?? 24} 小时的语音缓存文件，是否继续？`,
      '清理过期缓存',
      { type: 'warning', confirmButtonText: '清理', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  cleaning.value = true
  try {
    const data = await cleanupTtsCache()
    ElMessage.success(`清理完成，共删除 ${data.removed ?? 0} 个缓存文件`)
    await loadCache()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    cleaning.value = false
  }
}

async function onClear() {
  try {
    await ElMessageBox.confirm('确定清空全部语音缓存？该操作不可恢复。', '清空全部缓存', {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  clearing.value = true
  try {
    const data = await clearTtsCache()
    ElMessage.success(`已清空 ${data.removed ?? 0} 个缓存文件`)
    await loadCache()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    clearing.value = false
  }
}

async function onSynthesize() {
  if (synthesizing.value || saving.value) return
  const text = preview.text.trim()
  if (!text) {
    ElMessage.warning('请输入试听文本')
    return
  }

  synthesizing.value = true
  preview.error = ''
  preview.result = null
  try {
    if (!await saveSettings(false)) {
      preview.error = '语音设置保存失败，请检查配置后重试'
      return
    }
    const data = await synthesize({ text }, form.timeout)
    if (data.success) {
      preview.result = data
      ElMessage.success('语音生成成功')
    } else {
      preview.error = data.error || '语音合成失败，请检查所选服务的配置与网络'
    }
  } catch {
    preview.error = '语音合成请求失败，请检查服务日志或稍后重试'
  } finally {
    synthesizing.value = false
  }
}

onMounted(loadAll)
</script>

<style scoped>
.settings-layout {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  align-items: start;
  gap: 24px;
}

.settings-aside {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 24px;
}

.form-section + .form-section {
  margin-top: 8px;
  padding-top: 24px;
  border-top: 1px solid var(--yx-line);
}

.section-heading {
  margin-bottom: 20px;
}

.section-heading h4 {
  margin: 0 0 4px;
  color: var(--yx-text);
  font-size: 14px;
  font-weight: 600;
}

.section-heading p,
.panel-description {
  margin: 0;
  color: var(--yx-muted);
  font-size: 13px;
  line-height: 1.7;
}

.panel-description {
  margin: -8px 0 20px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}

.span-2 {
  grid-column: span 2;
}

.form-grid :deep(.el-input-number) {
  width: 100%;
}

.field-block {
  width: 100%;
}

.field-tip {
  width: 100%;
  margin-top: 5px;
  line-height: 1.7;
}

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

.cache-dir {
  display: inline-block;
  max-width: 100%;
  word-break: break-all;
}

.cache-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 16px 0;
}

.preview-toolbar {
  align-items: flex-start;
  flex-direction: column;
  margin: 12px 0 0;
}

.preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  margin-top: 24px;
  min-height: 200px;
  justify-content: center;
  padding: 32px 16px;
  border-top: 1px solid var(--yx-line);
  color: var(--yx-muted);
  font-size: 12px;
  line-height: 1.7;
  text-align: center;
}

.preview-empty strong {
  color: var(--yx-text-2);
  font-size: 14px;
  font-weight: 500;
}

.preview-result {
  margin-top: 16px;
  padding-top: 20px;
  border-top: 1px solid var(--yx-line);
}

.tts-audio {
  width: 100%;
  max-width: 560px;
}

.file-path {
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--yx-elevated);
  word-break: break-all;
}

@media (max-width: 1100px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 680px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: auto;
  }
}
</style>
