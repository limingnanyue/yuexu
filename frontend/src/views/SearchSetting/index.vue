<template>
  <div class="yx-page">
    <PageHeader title="联网搜索" description="DeepSeek Search API、时效问题自动检索">
      <el-tag :type="form.enabled ? 'success' : 'info'" effect="plain" size="small">
        {{ form.enabled ? '已启用' : '已停用' }}
      </el-tag>
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
    </PageHeader>

    <div class="yx-hint">
      联网搜索与 LLM 对话解耦：命中触发条件时先检索并生成摘要，再按需注入上下文；搜索失败会自动跳过，不影响基础对话。
    </div>

    <el-alert
      v-if="!auth.isOwner"
      title="仅超级主人可修改搜索配置，当前页面为只读模式"
      type="warning"
      show-icon
      :closable="false"
    />

    <div class="settings-layout" v-loading="loading">
      <section class="yx-card settings-main" aria-labelledby="search-config-title">
        <div class="yx-card-title">
          <h3 id="search-config-title">搜索配置</h3>
          <el-tag size="small" effect="plain" type="info">{{ form.provider || 'deepseek' }}</el-tag>
        </div>

        <el-form :model="form" label-position="top" :disabled="!auth.isOwner" @submit.prevent="save">
          <section class="form-section" aria-labelledby="search-service-title">
            <div class="section-heading">
              <h4 id="search-service-title">服务连接</h4>
              <p>连接搜索服务，配置访问凭证。</p>
            </div>
            <div class="form-grid">
            <el-form-item label="启用联网搜索">
              <div class="switch-line">
                <el-switch v-model="form.enabled" aria-label="启用联网搜索" />
                <span class="muted small">关闭后自动检索与手动搜索都会跳过</span>
              </div>
            </el-form-item>

            <el-form-item label="服务商">
              <el-select v-model="form.provider" style="width: 100%">
                <el-option label="DeepSeek Search" value="deepseek" />
              </el-select>
            </el-form-item>

            <el-form-item label="接口地址 base_url">
              <el-input v-model="form.base_url" placeholder="https://api.deepseek.com" />
            </el-form-item>

            <el-form-item label="接口路径 endpoint">
              <el-input v-model="form.endpoint" placeholder="/v1/search" />
            </el-form-item>

            <el-form-item label="API Key" class="span-2">
              <el-input
                v-model="form.api_key"
                type="password"
                show-password
                placeholder="留空表示不修改"
                autocomplete="off"
              />
              <div class="field-hint">留空或保持掩码表示不修改；后端会忽略全 * 值。</div>
            </el-form-item>
            </div>
          </section>

          <section class="form-section" aria-labelledby="search-policy-title">
            <div class="section-heading">
              <h4 id="search-policy-title">检索策略</h4>
              <p>控制结果规模、等待时间与自动检索方式。</p>
            </div>
            <div class="form-grid">
            <el-form-item label="结果条数 top_k">
              <el-input-number
                v-model="form.top_k"
                :min="1"
                :max="20"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>

            <el-form-item label="摘要最大字符数">
              <el-input-number
                v-model="form.max_summary_chars"
                :min="100"
                :max="8000"
                :step="100"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>

            <el-form-item label="请求超时（秒）">
              <el-input-number
                v-model="form.timeout"
                :min="1"
                :max="120"
                controls-position="right"
                style="width: 100%"
              />
            </el-form-item>

            <el-form-item label="时效问题自动检索">
              <div class="switch-line">
                <el-switch v-model="form.auto_trigger" aria-label="时效问题自动检索" />
                <span class="muted small">命中关键词或包含问号时自动触发</span>
              </div>
            </el-form-item>
            </div>
          </section>
        </el-form>

        <section class="form-section keyword-section" aria-labelledby="search-keyword-title">
        <div class="section-heading">
          <h4 id="search-keyword-title">时效关键词</h4>
          <p>命中任一关键词，或包含问号时，可自动发起检索。</p>
        </div>
        <div class="keyword-list">
          <el-tag
            v-for="(keyword, index) in keywords"
            :key="`${keyword}-${index}`"
            size="small"
            effect="plain"
          >
            {{ keyword }}
          </el-tag>
          <span v-if="!keywords.length" class="muted small">暂无关键词（由后端配置提供）</span>
        </div>
        <div class="yx-hint keyword-hint">
          自动触发规则：启用「时效问题自动检索」后，用户消息命中上述任一关键词，或包含问号（? / ？），将自动发起搜索；也可以在对话中通过命令手动触发。
        </div>
        </section>

        <div class="form-actions">
          <span class="muted small">保存后新的搜索请求立即生效</span>
          <el-button
            type="primary"
            :loading="saving"
            :disabled="!auth.isOwner"
            @click="save"
          >
            保存配置
          </el-button>
        </div>
      </section>

      <section class="yx-card settings-preview" aria-labelledby="search-preview-title">
        <div class="yx-card-title">
          <h3 id="search-preview-title">测试搜索</h3>
          <el-tag size="small" effect="plain">实时调用</el-tag>
        </div>
        <p class="panel-description">使用已保存的配置，检查搜索结果与上下文摘要。</p>

        <div class="test-query">
          <el-input
            v-model="testQuery"
            aria-label="搜索测试问题"
            placeholder="输入要搜索的问题，例如：今天上海天气"
            clearable
            @keyup.enter="runTest"
          />
          <el-button
            type="primary"
            :icon="Search"
            :loading="testing"
            :disabled="!testQuery.trim()"
            @click="runTest"
          >
            测试搜索
          </el-button>
        </div>

        <div class="test-result" v-loading="testing">
          <template v-if="testResult">
            <div class="result-meta">
              <el-tag
                :type="testResult.success ? 'success' : 'danger'"
                effect="plain"
                size="small"
              >
                {{ testResult.success ? '搜索成功' : '搜索失败' }}
              </el-tag>
              <span class="muted small">耗时 {{ testResult.latency_ms ?? 0 }} ms</span>
              <span v-if="testResult.items?.length" class="muted small">
                共 {{ testResult.items.length }} 条结果
              </span>
            </div>

            <el-alert
              v-if="!testResult.success"
              :title="testResult.error || '搜索失败，请检查配置与网络'"
              type="error"
              show-icon
              :closable="false"
            />

            <div v-if="testResult.summary" class="summary-block">
              <div class="section-label">搜索摘要</div>
              <div class="summary-text">{{ testResult.summary }}</div>
            </div>

            <div v-if="testResult.items?.length" class="result-list">
              <div class="section-label">搜索结果</div>
              <a
                v-for="(item, index) in testResult.items"
                :key="item.url || index"
                :href="item.url"
                target="_blank"
                rel="noopener noreferrer"
                class="result-item"
              >
                <div class="result-title">
                  <span class="mono muted">{{ index + 1 }}</span>
                  <span>{{ item.title || item.url || '未命名结果' }}</span>
                </div>
                <div v-if="item.snippet" class="result-snippet">{{ item.snippet }}</div>
                <div v-if="item.url" class="result-url mono">{{ item.url }}</div>
              </a>
            </div>

            <el-empty
              v-else-if="testResult.success"
              description="搜索成功，但没有返回结果"
              :image-size="80"
            />
          </template>

          <div v-else class="preview-empty">
            <el-icon :size="24" aria-hidden="true"><Search /></el-icon>
            <strong>等待搜索结果</strong>
            <span>输入问题后点击「测试搜索」，在这里查看摘要与来源。</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import { getSearchSettings, testSearch, updateSearchSettings } from '@/api/search'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const keywords = ref([])
const testQuery = ref('')
const testResult = ref(null)
const originalApiKey = ref('')

const form = reactive({
  enabled: false,
  provider: 'deepseek',
  base_url: '',
  endpoint: '',
  api_key: '',
  top_k: 5,
  max_summary_chars: 1500,
  timeout: 15,
  auto_trigger: true,
})

function applySettings(data) {
  form.enabled = Boolean(data.enabled)
  form.provider = data.provider || 'deepseek'
  form.base_url = data.base_url || ''
  form.endpoint = data.endpoint || ''
  form.api_key = data.api_key || ''
  form.top_k = Number(data.top_k ?? 5)
  form.max_summary_chars = Number(data.max_summary_chars ?? 1500)
  form.timeout = Number(data.timeout ?? 15)
  form.auto_trigger = Boolean(data.auto_trigger)
  keywords.value = Array.isArray(data.freshness_keywords) ? data.freshness_keywords : []
  originalApiKey.value = form.api_key
}

async function load() {
  loading.value = true
  try {
    const data = await getSearchSettings()
    applySettings(data || {})
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!auth.isOwner) return
  saving.value = true
  try {
    const payload = {
      enabled: form.enabled,
      provider: form.provider,
      base_url: form.base_url,
      endpoint: form.endpoint,
      top_k: form.top_k ?? 5,
      max_summary_chars: form.max_summary_chars ?? 1500,
      timeout: form.timeout ?? 15,
      auto_trigger: form.auto_trigger,
    }
    const apiKey = form.api_key.trim()
    if (apiKey && apiKey !== originalApiKey.value) {
      payload.api_key = apiKey
    }
    await updateSearchSettings(payload)
    ElMessage.success('搜索配置已保存')
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    saving.value = false
  }
}

async function runTest() {
  const query = testQuery.value.trim()
  if (!query) {
    ElMessage.warning('请输入要搜索的内容')
    return
  }
  testing.value = true
  try {
    testResult.value = await testSearch(query)
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    testing.value = false
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

.form-section + .form-section,
.keyword-section {
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

.form-grid .span-2 {
  grid-column: span 2;
}

.switch-line {
  display: flex;
  gap: 10px;
  min-height: 32px;
  align-items: flex-start;
}

.switch-line .el-switch {
  flex: none;
}

.switch-line .small {
  padding-top: 6px;
}

.field-hint {
  width: 100%;
  margin-top: 4px;
  color: var(--yx-muted);
  font-size: 12px;
  line-height: 1.6;
}

.form-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: space-between;
  flex-wrap: wrap;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--yx-line);
}

.section-label {
  margin-bottom: 10px;
  color: var(--yx-text-2);
  font-size: 12.5px;
  font-weight: 600;
}

.keyword-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.keyword-hint { margin-top: 16px; }

.test-query {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.test-query .el-input {
  flex: 1;
}

.test-query .el-button {
  align-self: flex-start;
}

.test-result {
  margin-top: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.preview-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  justify-content: center;
  min-height: 220px;
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

.result-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
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

.result-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.result-item {
  display: block;
  padding: 12px 14px;
  border: 1px solid var(--yx-line);
  border-radius: 12px;
  background: var(--yx-elevated);
  color: inherit;
  transition: border-color 0.16s ease, background-color 0.16s ease;
}

.result-item:hover {
  border-color: var(--yx-accent);
  background: var(--yx-elevated);
}

.result-title {
  display: flex;
  gap: 8px;
  color: var(--yx-text);
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.result-snippet {
  margin-top: 5px;
  color: var(--yx-text-2);
  font-size: 12.5px;
  line-height: 1.7;
  word-break: break-word;
}

.result-url {
  margin-top: 6px;
  color: var(--yx-accent);
  font-size: 11.5px;
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

  .form-grid .span-2 {
    grid-column: auto;
  }

  .test-query {
    flex-direction: column;
  }
}
</style>
