<template>
  <div class="yx-page">
    <PageHeader title="表情库" description="管理表情标签、关键词与权重">
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      <el-button type="primary" :icon="UploadFilled" @click="openUpload">上传表情</el-button>
    </PageHeader>

    <div class="yx-hint">
      LLM 输出 <code>[开心]</code> 这类标签时会自动替换为对应表情；表情只写入消息，不写入长期记忆。
      请在私聊中发消息测试表情，控制台不主动发送测试消息。
    </div>

    <div class="yx-card emoji-library">
      <div class="yx-card-title">
        <h3>表情列表</h3>
        <span class="muted small">共 {{ total }} 个表情</span>
      </div>

      <div v-loading="loading" class="emoji-grid">
        <div v-for="item in emojis" :key="item.id" class="emoji-card">
          <div class="emoji-preview">
            <img
              v-if="item.url && !broken[item.id]"
              :src="item.url"
              :alt="item.key"
              loading="lazy"
              decoding="async"
              @error="onImageError(item.id)"
            />
            <div v-else class="emoji-placeholder">
              <el-icon :size="30"><Picture /></el-icon>
              <span class="mono">{{ item.file_path || '未登记文件' }}</span>
            </div>
          </div>

          <div class="emoji-body">
            <div class="emoji-head">
              <span class="emoji-key mono">{{ item.key }}</span>
              <el-tag size="small" effect="plain">{{ item.category || 'default' }}</el-tag>
            </div>
            <div class="emoji-alias">{{ item.alias || '未设置别名' }}</div>

            <div class="emoji-meta">
              <span class="muted small">权重 {{ item.weight ?? 1 }}</span>
              <el-switch
                :model-value="item.enabled"
                :aria-label="`启用表情 ${item.key}`"
                :loading="isBusy(item, 'toggle')"
                @change="(value) => onToggle(item, value)"
              />
            </div>

            <div class="emoji-actions">
              <el-button link type="primary" size="small" @click="copyKey(item)">
                复制 key
              </el-button>
              <el-button link type="primary" size="small" disabled title="请在私聊中发消息测试表情" @click="openTest(item)">
                测试发送
              </el-button>
              <el-button link type="primary" size="small" @click="openEdit(item)">编辑</el-button>
              <el-button link type="danger" size="small" @click="onDelete(item)">删除</el-button>
            </div>
          </div>
        </div>

        <el-empty
          v-if="!loading && !emojis.length"
          description="暂无表情，先上传一个吧"
          class="emoji-empty"
        />
      </div>
    </div>

    <el-dialog
      v-model="uploadVisible"
      title="上传表情"
      width="520px"
      :close-on-click-modal="false"
      @closed="resetUpload"
    >
      <el-form :model="uploadForm" label-position="top">
        <el-form-item label="表情图片" required>
          <el-upload
            ref="uploadRef"
            class="upload-block"
            drag
            :auto-upload="false"
            :limit="1"
            accept="image/*"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽图片到此处，或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">支持 png / jpg / jpeg / gif / webp</div>
            </template>
          </el-upload>
        </el-form-item>

        <el-form-item label="key" required>
          <el-input v-model="uploadForm.key" placeholder="默认取文件名，用于标签匹配" />
        </el-form-item>

        <el-form-item label="别名">
          <el-input v-model="uploadForm.alias" placeholder="例如：开心" />
        </el-form-item>

        <el-form-item label="分类">
          <el-input v-model="uploadForm.category" placeholder="default" />
        </el-form-item>

        <el-form-item label="权重">
          <el-input-number v-model="uploadForm.weight" :min="1" :max="99" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">上传</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="editVisible"
      title="编辑表情"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form :model="editForm" label-position="top">
        <el-form-item label="别名">
          <el-input v-model="editForm.alias" placeholder="例如：开心" />
        </el-form-item>

        <el-form-item label="分类">
          <el-input v-model="editForm.category" placeholder="default" />
        </el-form-item>

        <el-form-item label="权重">
          <el-input-number v-model="editForm.weight" :min="1" :max="99" />
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="editForm.enabled" />
        </el-form-item>

        <el-form-item label="文件路径">
          <el-input :model-value="editForm.file_path || '—'" readonly />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSaving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="testVisible"
      title="测试发送"
      width="500px"
      :close-on-click-modal="false"
    >
      <div v-if="testEmoji" class="yx-hint test-hint">
        主动测试发送已停用，请在私聊中发消息测试表情。
      </div>

      <el-form :model="testForm" label-width="88px" disabled>
        <el-form-item label="机器人账号" required>
          <el-select v-model="testForm.bot_id" placeholder="选择发送账号" style="width: 100%">
            <el-option
              v-for="item in accounts"
              :key="item.id"
              :label="accountLabel(item)"
              :disabled="!channelInfo(item.platform).media"
              :value="item.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="目标类型">
          <el-radio-group v-model="testForm.target_type">
            <el-radio value="group">群聊</el-radio>
            <el-radio value="private">私聊</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="目标 ID" required>
          <el-input
            v-model="testForm.target_id"
            :placeholder="testForm.target_type === 'group' ? '群号' : '对方 QQ / 微信 ID'"
          />
        </el-form-item>
      </el-form>

      <el-alert
        v-if="testResult"
        :type="testResult.success ? 'success' : 'error'"
        :title="testResult.success ? '发送成功' : '发送失败'"
        :description="
          testResult.success
            ? `已提交表情「${testEmoji?.key || ''}」`
            : testResult.error || '请检查账号状态与目标 ID'
        "
        show-icon
        :closable="false"
      />

      <template #footer>
        <el-button @click="testVisible = false">关闭</el-button>
        <el-button type="primary" disabled :loading="testing" @click="submitTest">发送</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Picture, Refresh, UploadFilled } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import { listAccounts } from '@/api/account'
import { channelInfo } from '@/utils/channels'
import { platformLabel } from '@/utils/format'
import {
  deleteEmoji,
  listEmojis,
  testSendEmoji,
  updateEmoji,
  uploadEmoji,
} from '@/api/emoji'

const emojis = ref([])
const total = ref(0)
const accounts = ref([])
const loading = ref(false)
const busyId = ref('')
const broken = reactive({})

const uploadVisible = ref(false)
const uploadRef = ref(null)
const selectedFile = ref(null)
const uploading = ref(false)
const uploadForm = reactive({ key: '', alias: '', category: 'default', weight: 1 })

const editVisible = ref(false)
const editSaving = ref(false)
const editId = ref('')
const editForm = reactive({ alias: '', category: 'default', weight: 1, enabled: true, file_path: '' })

const testVisible = ref(false)
const testing = ref(false)
const testEmoji = ref(null)
const testResult = ref(null)
const testForm = reactive({ bot_id: '', target_type: 'group', target_id: '' })

function accountLabel(item) {
  const platform = item.platform_label || platformLabel(item.platform)
  return `${item.name || item.id}（${platform}）`
}

function isBusy(item, action) {
  return busyId.value === `${item.id}:${action}`
}

function onImageError(id) {
  broken[id] = true
}

async function load() {
  loading.value = true
  try {
    const data = await listEmojis({ page: 1, page_size: 200 })
    emojis.value = data.items || []
    total.value = data.total ?? emojis.value.length
    Object.keys(broken).forEach((key) => delete broken[key])
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    loading.value = false
  }
}

async function loadAccounts() {
  try {
    const data = await listAccounts()
    accounts.value = Array.isArray(data) ? data : []
  } catch {
    accounts.value = []
  }
}

async function onToggle(item, enabled) {
  busyId.value = `${item.id}:toggle`
  try {
    const data = await updateEmoji(item.id, { enabled })
    Object.assign(item, data)
    ElMessage.success(enabled ? '表情已启用' : '表情已停用')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    busyId.value = ''
  }
}

async function copyKey(item) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(item.key)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = item.key
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success(`已复制 key：${item.key}`)
  } catch {
    ElMessage.warning('复制失败，请手动选择 key')
  }
}

function openUpload() {
  uploadForm.key = ''
  uploadForm.alias = ''
  uploadForm.category = 'default'
  uploadForm.weight = 1
  selectedFile.value = null
  uploadVisible.value = true
}

function resetUpload() {
  uploadRef.value?.clearFiles()
  selectedFile.value = null
}

function handleFileChange(uploadFile) {
  selectedFile.value = uploadFile.raw || null
  if (!uploadForm.key) {
    uploadForm.key = String(uploadFile.name || '').replace(/\.[^.]+$/, '')
  }
}

function handleFileRemove() {
  selectedFile.value = null
}

async function submitUpload() {
  if (!selectedFile.value) {
    ElMessage.warning('请选择表情图片')
    return
  }
  const key = uploadForm.key.trim()
  if (!key) {
    ElMessage.warning('请填写表情 key')
    return
  }

  const data = new FormData()
  data.append('file', selectedFile.value)
  data.append('key', key)
  data.append('alias', uploadForm.alias.trim())
  data.append('category', uploadForm.category.trim() || 'default')
  data.append('weight', String(uploadForm.weight || 1))

  uploading.value = true
  try {
    await uploadEmoji(data)
    ElMessage.success('表情已上传')
    uploadVisible.value = false
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    uploading.value = false
  }
}

function openEdit(item) {
  editId.value = item.id
  Object.assign(editForm, {
    alias: item.alias || '',
    category: item.category || 'default',
    weight: item.weight ?? 1,
    enabled: item.enabled !== false,
    file_path: item.file_path || '',
  })
  editVisible.value = true
}

async function saveEdit() {
  editSaving.value = true
  try {
    await updateEmoji(editId.value, {
      alias: editForm.alias.trim(),
      category: editForm.category.trim() || 'default',
      weight: editForm.weight || 1,
      enabled: editForm.enabled,
    })
    ElMessage.success('表情已更新')
    editVisible.value = false
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    editSaving.value = false
  }
}

function openTest(item) {
  testEmoji.value = item
  testResult.value = null
  testForm.target_id = ''
  if (!testForm.bot_id && accounts.value.length) {
    testForm.bot_id = accounts.value[0].id
  }
  testVisible.value = true
}

async function submitTest() {
  if (!testForm.bot_id) {
    ElMessage.warning('请选择机器人账号')
    return
  }
  if (!testForm.target_id.trim()) {
    ElMessage.warning('请填写目标 ID')
    return
  }

  testing.value = true
  testResult.value = null
  try {
    const data = await testSendEmoji(testEmoji.value.id, {
      bot_id: testForm.bot_id,
      target_type: testForm.target_type,
      target_id: testForm.target_id.trim(),
    })
    testResult.value = { success: !!data.success, error: data.error || '' }
  } catch {
    testResult.value = { success: false, error: '测试发送请求失败，请查看服务日志' }
  } finally {
    testing.value = false
  }
}

async function onDelete(item) {
  try {
    await ElMessageBox.confirm(`确定删除表情「${item.key}」？删除后不可恢复。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  try {
    await deleteEmoji(item.id)
    ElMessage.success('表情已删除')
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  }
}

onMounted(() => {
  load()
  loadAccounts()
})
</script>

<style scoped>
.emoji-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 200px), 1fr));
  gap: 16px;
  min-height: 140px;
}

.emoji-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--yx-line);
  border-radius: var(--yx-radius);
  background: var(--yx-card);
  transition: border-color .16s ease;
}

.emoji-card:hover {
  border-color: var(--yx-accent);
}

.emoji-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 150px;
  padding: 12px;
  background: var(--yx-elevated);
  border-bottom: 1px solid var(--yx-line);
}

.emoji-preview img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.emoji-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  color: var(--yx-muted);
  font-size: 11px;
  line-height: 1.5;
  text-align: center;
  word-break: break-all;
}

.emoji-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px 14px;
}

.emoji-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.emoji-head .el-tag { flex: none; max-width: 50%; overflow: hidden; text-overflow: ellipsis; }

.emoji-key {
  overflow: hidden;
  color: var(--yx-text);
  font-size: 13.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.emoji-alias {
  color: var(--yx-text-2);
  font-size: 12.5px;
  overflow-wrap: anywhere;
}

.emoji-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}

.emoji-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
  padding-top: 10px;
  border-top: 1px solid var(--yx-line);
}

.emoji-actions .el-button {
  margin-left: 0;
}

.emoji-empty {
  grid-column: 1 / -1;
}

.upload-block {
  width: 100%;
}

.upload-block :deep(.el-upload) {
  width: 100%;
}

.test-hint {
  margin-bottom: 16px;
}

@media (max-width: 760px) {
  .emoji-grid { gap: 12px; }
  .emoji-preview { height: 172px; }
  .emoji-actions :deep(.el-button) { min-height: 36px; }
}
</style>
