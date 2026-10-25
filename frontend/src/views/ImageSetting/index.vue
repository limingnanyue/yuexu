<template>
  <div class="yx-page">
    <PageHeader title="AI 生图" description="接入 OpenAI 兼容图片生成模型，在控制台预览或聊天中调用">
      <el-button :icon="Refresh" :loading="loading" :disabled="saving || generating" @click="load">刷新</el-button>
    </PageHeader>

    <div class="yx-hint">
      保存并启用且配置可用后，QQ 个人账号（NapCat）的私聊会由 AI 按话题自主决定是否配图，也可直接说“发张图片给我”，无需指令，并非每条都配图。QQ 语音通话中的图片会发到同一 QQ 私聊，文字继续通过通话播放。图片由 AI 生成，不冒充实拍；生图失败保留文字，可能产生生图费用。仍可发送 <code>/image 图片描述</code> 或 <code>/draw 图片描述</code>，指令发图支持 QQ 个人账号与微信个人账号（Gewechat）。QQ 个人账号的私聊惦记与活力 Agent 继续支持自动配图，活力 Agent 预览不调用生图。QQ 官方机器人和微信 ClawBot 暂不支持媒体。
    </div>

    <el-alert v-if="loadError" :title="loadError" type="error" show-icon :closable="false" />

    <div class="settings-layout" v-loading="loading">
      <section class="yx-card settings-main" aria-labelledby="image-config-title">
        <div class="yx-card-title">
          <h3 id="image-config-title">生图模型配置</h3>
          <el-tag :type="form.enabled ? 'success' : 'info'" effect="plain" size="small">{{ form.enabled ? '已启用' : '已停用' }}</el-tag>
        </div>

        <el-form :model="form" label-position="top" :disabled="saving || generating">
          <section class="form-section" aria-labelledby="image-service-title">
            <div class="section-heading">
              <h4 id="image-service-title">服务连接</h4>
              <p>接入图片生成模型，设置访问凭证。</p>
            </div>
          <el-form-item label="启用生图">
            <div class="switch-line">
              <el-switch v-model="form.enabled" aria-label="启用生图" />
              <span class="muted small">允许控制台、聊天指令及 QQ 个人账号主动消息调用生图，按服务商计费</span>
            </div>
          </el-form-item>
          <el-form-item label="接口地址 base_url">
            <el-input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
          </el-form-item>
          <el-form-item label="API Key">
            <div class="field-block">
              <el-input v-model="form.api_key" type="password" show-password autocomplete="off" />
              <div class="muted small field-tip">保持掩码保留密钥，清空则删除。更换服务地址后请重新填写 API Key。</div>
            </div>
          </el-form-item>
          <el-form-item label="生图模型">
            <div class="field-block">
              <el-input v-model="form.model" placeholder="填写服务商提供的模型 ID，例如 gpt-image-1" />
              <div class="muted small field-tip">模型名称与支持的参数以所接入服务商为准。</div>
            </div>
          </el-form-item>
          </section>

          <section class="form-section" aria-labelledby="image-parameters-title">
            <div class="section-heading">
              <h4 id="image-parameters-title">生成参数</h4>
              <p>设置图片尺寸、等待时间与本地缓存。</p>
            </div>
            <div class="form-grid">
          <el-form-item label="图片尺寸" class="span-2">
            <div class="field-block">
              <el-input v-model="form.size" placeholder="例如 1024x1024、1536x1024 或 auto" />
              <div class="muted small field-tip">直接填写模型支持的尺寸，每次生成 1 张图片。</div>
            </div>
          </el-form-item>
          <el-form-item label="请求超时（秒）">
            <el-input-number v-model="form.timeout" :min="1" :max="300" controls-position="right" />
          </el-form-item>
          <el-form-item label="缓存有效期（小时）">
            <div class="field-block">
              <el-input-number v-model="form.cache_ttl_hours" :min="0" :max="720" controls-position="right" />
              <div class="muted small field-tip">0 表示不自动清理；生成图片保存在本地缓存。</div>
            </div>
          </el-form-item>
            </div>
          </section>
        </el-form>

        <div class="form-actions">
          <span class="muted small">修改后保存生效</span>
          <el-button type="primary" :loading="saving" :disabled="loading || !!loadError || generating" @click="saveSettings()">保存设置</el-button>
        </div>
      </section>

      <section class="yx-card settings-preview" aria-labelledby="image-preview-title">
        <div class="yx-card-title">
          <h3 id="image-preview-title">生成预览</h3>
          <el-tag v-if="settings" :type="settings.available ? 'success' : 'warning'" size="small" effect="plain">{{ settings.available ? '服务已配置' : '请完善配置并启用' }}</el-tag>
        </div>
        <p class="panel-description">描述一个画面，验证模型连接与生成效果。</p>

        <el-form label-position="top" @submit.prevent="onGenerate">
          <el-form-item label="图片描述">
            <el-input v-model="preview.prompt" type="textarea" :rows="5" :maxlength="4000" show-word-limit placeholder="描述画面的主体、环境和风格，例如：月光下坐在窗边的小机器人，温暖的水彩插画。" />
          </el-form-item>
          <el-button type="primary" :icon="Picture" :loading="generating" :disabled="loading || saving || !!loadError || !form.enabled || !preview.prompt.trim()" @click="onGenerate">保存并生成图片</el-button>
        </el-form>

        <p class="muted small field-tip">请先启用生图。生成会保存当前设置，并将描述发送至所配置的服务商，可能产生调用费用。图片由 AI 生成。</p>

        <el-alert v-if="preview.error" :title="preview.error" type="error" show-icon :closable="false" />
        <div v-if="preview.result" class="preview-result">
          <el-image v-if="preview.result.url" :src="preview.result.url" :preview-src-list="[preview.result.url]" fit="contain" class="generated-image" :alt="preview.prompt" preview-teleported>
            <template #error><div class="yx-empty">图片加载失败，请重新生成或检查服务状态。</div></template>
          </el-image>
          <div v-else class="mono">文件路径：{{ preview.result.file_path || '—' }}</div>
        </div>
        <div v-else-if="!preview.error && !generating" class="preview-empty">
          <el-icon :size="24" aria-hidden="true"><Picture /></el-icon>
          <strong>等待画面生成</strong>
          <span>填写图片描述并生成，图片会显示在这里。</span>
        </div>
        <p v-if="generating" class="muted small" role="status">正在生成图片，请稍候…</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Picture, Refresh } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import { generateImage, getImageSettings, updateImageSettings } from '@/api/image'

const settings = ref(null)
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const generating = ref(false)
const form = reactive({
  enabled: false,
  base_url: 'https://api.openai.com/v1',
  api_key: '',
  model: '',
  size: '1024x1024',
  timeout: 120,
  cache_ttl_hours: 24,
})
const preview = reactive({ prompt: '', result: null, error: '' })

function applySettings(data) {
  settings.value = data
  for (const key of Object.keys(form)) {
    if (data[key] !== undefined) form[key] = data[key]
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    applySettings(await getImageSettings())
  } catch {
    loadError.value = '生图配置读取失败，请点击刷新后重试'
  } finally {
    loading.value = false
  }
}

async function saveSettings(notify = true) {
  if (saving.value || loadError.value) return false
  saving.value = true
  try {
    const data = await updateImageSettings({
      ...form,
      base_url: form.base_url.trim(),
      api_key: form.base_url.trim() !== settings.value?.base_url && /^\*+$/.test(form.api_key) ? '' : form.api_key,
      model: form.model.trim(),
      size: form.size.trim(),
      timeout: form.timeout ?? 120,
      cache_ttl_hours: form.cache_ttl_hours ?? 24,
    })
    applySettings(data.image_generation)
    if (notify) ElMessage.success('生图配置已保存')
    return true
  } catch {
    return false
  } finally {
    saving.value = false
  }
}

async function onGenerate() {
  if (generating.value || saving.value) return
  const prompt = preview.prompt.trim()
  if (!prompt) {
    ElMessage.warning('请输入图片描述')
    return
  }
  generating.value = true
  preview.error = ''
  preview.result = null
  try {
    if (!await saveSettings(false)) {
      preview.error = '生图设置保存失败，请检查配置后重试'
      return
    }
    const data = await generateImage({ prompt }, form.timeout)
    if (data.success) {
      preview.result = data
      ElMessage.success('图片生成成功')
    } else {
      preview.error = data.error || '图片生成失败，请检查服务商配置与网络后重试'
    }
  } catch {
    preview.error = '图片生成请求失败，请检查服务状态后重试'
  } finally {
    generating.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings-layout {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  align-items: start;
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

.span-2 { grid-column: span 2; }
.form-grid :deep(.el-input-number) { width: 100%; }
.switch-line { display: flex; align-items: flex-start; gap: 12px; }
.switch-line .el-switch { flex: none; }
.switch-line .small { padding-top: 6px; }
.field-block { width: 100%; }
.field-tip { width: 100%; margin-top: 6px; line-height: 1.7; }
.form-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-top: 8px; padding-top: 20px; border-top: 1px solid var(--yx-line); }
.preview-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; min-height: 240px; margin-top: 24px; padding: 32px 16px; border-top: 1px solid var(--yx-line); color: var(--yx-muted); font-size: 12px; line-height: 1.7; text-align: center; }
.preview-empty strong { color: var(--yx-text-2); font-size: 14px; font-weight: 500; }
.preview-result { margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--yx-line); overflow-wrap: anywhere; }
.generated-image { display: block; width: 100%; min-height: 200px; max-height: 560px; border-radius: var(--yx-radius); background: var(--yx-bg); }
.generated-image :deep(.el-image__inner) { max-height: 560px; object-fit: contain; }

@media (max-width: 1100px) {
  .settings-layout { grid-template-columns: 1fr; }
}

@media (max-width: 680px) {
  .form-grid { grid-template-columns: 1fr; }
  .span-2 { grid-column: auto; }
}
</style>
