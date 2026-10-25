<template>
  <div class="yx-page">
    <PageHeader title="情感状态" description="每段关系的心情、好感与信任，随对话自动演化">
      <el-button type="danger" plain :icon="Delete" :loading="clearing" @click="clearAll">
        清空全部
      </el-button>
    </PageHeader>

    <el-alert
      class="intro-alert"
      type="info"
      :closable="false"
      show-icon
      title="机器人会记住和每个人的关系：心情随聊天起伏、好感与信任慢慢积累，并在回复中自然体现。这里可以查看与手动校准。"
    />

    <div class="yx-card search-card">
      <div class="yx-toolbar search-toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索用户 ID / 心情"
          clearable
          :prefix-icon="Search"
          class="search-input"
          aria-label="搜索用户 ID 或心情"
          @keyup.enter="search"
          @clear="search"
        />
        <el-button :icon="Search" @click="search">搜索</el-button>
        <div class="yx-toolbar-spacer"></div>
        <span class="muted small">共 {{ total }} 段关系</span>
      </div>
    </div>

    <div v-loading="loading" class="emotion-list">
      <div v-if="states.length" class="yx-grid yx-grid-2">
        <div v-for="item in states" :key="item.id" class="yx-card emotion-card">
          <div class="emotion-head">
            <div class="emotion-who">
              <h3>{{ item.target_type === 'group' ? '群聊 ' + item.target_id : item.user_id || item.target_id }}</h3>
              <el-tag size="small" effect="plain" :type="stageTagType(item.relationship_stage)">
                {{ item.relationship_stage }}
              </el-tag>
            </div>
            <el-tag size="small" effect="plain" :type="moodTagType(item.mood_label)">
              {{ item.mood_label }}
            </el-tag>
          </div>

          <p v-if="item.mood_note" class="emotion-note">“{{ item.mood_note }}”</p>

          <div class="emotion-bars">
            <div class="bar-row">
              <span class="bar-label">好感</span>
              <el-progress
                :percentage="Math.round(item.affection)"
                :stroke-width="8"
                :color="affectionColor"
              />
            </div>
            <div class="bar-row">
              <span class="bar-label">信任</span>
              <el-progress
                :percentage="Math.round(item.trust)"
                :stroke-width="8"
                color="var(--el-color-success)"
              />
            </div>
          </div>

          <div class="emotion-meta muted small">
            <p v-if="item.current_activity"><span class="meta-label">当前动态</span>{{ item.current_activity }}</p>
            <p v-if="item.last_event"><span class="meta-label">最近触动</span>{{ item.last_event }}</p>
            <p v-if="item.last_inner_thought"><span class="meta-label">内心想法</span>{{ item.last_inner_thought }}</p>
            <p><span class="meta-label">已聊轮次</span>{{ item.interaction_count }}</p>
            <p><span class="meta-label">更新时间</span>{{ formatDateTime(item.updated_at) }}</p>
          </div>

          <div class="emotion-actions">
            <el-button link type="primary" :icon="Edit" @click="openEdit(item)">校准</el-button>
            <el-button
              link
              type="danger"
              :icon="RefreshLeft"
              :loading="resettingId === item.id"
              @click="resetItem(item)"
            >
              重置
            </el-button>
          </div>
        </div>
      </div>

      <div v-else-if="!loading" class="yx-card">
        <el-empty description="还没有情感记录，机器人收到第一条私聊或群聊消息后会自动开始积累" :image-size="72" />
      </div>
    </div>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      @current-change="load"
    />

    <el-dialog v-model="editVisible" title="校准情感状态" width="520px">
      <el-form label-position="top" @submit.prevent>
        <div class="form-grid">
          <el-form-item label="心情标签">
            <el-select v-model="editForm.mood_label" filterable allow-create>
              <el-option v-for="mood in MOODS" :key="mood.value" :label="mood.label" :value="mood.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="当前动态">
            <el-input v-model="editForm.current_activity" maxlength="60" placeholder="例如：在追剧" />
          </el-form-item>
        </div>
        <el-form-item label="心情描述">
          <el-input v-model="editForm.mood_note" maxlength="120" placeholder="当前内心状态的一句话" />
        </el-form-item>
        <el-form-item label="最近触动">
          <el-input v-model="editForm.last_event" maxlength="120" placeholder="最近影响情绪的一件事" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="好感度（0-100）">
            <el-input-number v-model="editForm.affection" :min="0" :max="100" />
          </el-form-item>
          <el-form-item label="信任度（0-100）">
            <el-input-number v-model="editForm.trust" :min="0" :max="100" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, RefreshLeft, Search } from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import { clearEmotions, listEmotions, resetEmotion, updateEmotion } from '@/api/emotion'
import { formatDateTime } from '@/utils/format'

const MOODS = [
  { label: '平静', value: '平静' },
  { label: '开心', value: '开心' },
  { label: '兴奋', value: '兴奋' },
  { label: '感动', value: '感动' },
  { label: '低落', value: '低落' },
  { label: '烦躁', value: '烦躁' },
  { label: '担心', value: '担心' },
  { label: '无聊', value: '无聊' },
]

const states = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const loading = ref(false)
const clearing = ref(false)
const resettingId = ref('')
const editVisible = ref(false)
const saving = ref(false)
const editId = ref('')
const editForm = ref({})

const affectionColor = [
  { color: '#d9a05b', percentage: 45 },
  { color: '#c99a5b', percentage: 65 },
  { color: '#b26e63', percentage: 85 },
  { color: '#a44a4a', percentage: 100 },
]

async function load() {
  loading.value = true
  try {
    const data = await listEmotions({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() || undefined,
    })
    states.value = data?.items || []
    total.value = data?.total || 0
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function stageTagType(stage) {
  return { 挚友: 'danger', 好朋友: 'warning', 熟人: 'success', 认识: 'primary', 初识: 'info' }[stage] || 'info'
}

function moodTagType(mood) {
  if (['开心', '兴奋', '感动'].includes(mood)) return 'success'
  if (['低落', '烦躁', '担心'].includes(mood)) return 'warning'
  return 'info'
}

function openEdit(item) {
  editId.value = item.id
  editForm.value = {
    mood_label: item.mood_label || '平静',
    mood_note: item.mood_note || '',
    affection: Math.round(item.affection ?? 30),
    trust: Math.round(item.trust ?? 30),
    current_activity: item.current_activity || '',
    last_event: item.last_event || '',
  }
  editVisible.value = true
}

async function saveEdit() {
  saving.value = true
  try {
    await updateEmotion(editId.value, editForm.value)
    ElMessage.success('已校准')
    editVisible.value = false
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    saving.value = false
  }
}

async function resetItem(item) {
  try {
    await ElMessageBox.confirm(
      '重置后这段关系的心情、好感与信任会清零重来，确定吗？',
      '重置情感状态',
      { type: 'warning', confirmButtonText: '重置', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  resettingId.value = item.id
  try {
    await resetEmotion(item.id)
    ElMessage.success('已重置')
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    resettingId.value = ''
  }
}

async function clearAll() {
  try {
    await ElMessageBox.confirm(
      '将清空所有关系的情感状态，机器人会从初识重新开始，确定吗？',
      '清空情感状态',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  clearing.value = true
  try {
    await clearEmotions()
    ElMessage.success('已清空')
    page.value = 1
    await load()
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    clearing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.intro-alert {
  margin-bottom: 0;
}

.search-card {
  padding: 16px 20px;
}

.search-toolbar {
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom: 0;
}

.search-input { width: 320px; max-width: 100%; }

.emotion-list {
  min-height: 160px;
}

.emotion-list .yx-grid {
  align-items: stretch;
}

.emotion-card {
  display: flex;
  flex-direction: column;
  transition: border-color 0.16s ease;
}

.emotion-card:hover, .emotion-card:focus-within {
  border-color: var(--el-color-primary-light-5);
}

.emotion-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.emotion-who {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.emotion-who h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--yx-text);
  overflow-wrap: anywhere;
}

.emotion-note {
  margin: 16px 0 0;
  color: var(--yx-text-2);
  font-size: 13px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.emotion-bars {
  margin-top: 20px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bar-row + .bar-row {
  margin-top: 10px;
}

.bar-label {
  width: 34px;
  flex-shrink: 0;
  font-size: 12.5px;
  color: var(--yx-text-2);
}

.bar-row :deep(.el-progress) {
  flex: 1;
}

.bar-row :deep(.el-progress__text) {
  font-size: 12px !important;
  min-width: 34px;
}

.emotion-meta {
  margin: 20px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.emotion-meta p {
  margin: 0;
  line-height: 1.6;
  word-break: break-word;
}

.meta-label {
  display: inline-block;
  margin-right: 8px;
  min-width: 56px;
  color: var(--yx-muted);
  font-size: 12px;
}

.emotion-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid var(--yx-line);
}

.emotion-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.form-grid :deep(.el-select), .form-grid :deep(.el-input-number) { width: 100%; }

@media (max-width: 700px) {
  .search-card { padding: 16px; }
  .search-input { flex: 1; min-width: 150px; }
  .search-toolbar .yx-toolbar-spacer { display: none; }
  .search-toolbar > .muted { flex-basis: 100%; }
  .emotion-actions :deep(.el-button) { min-height: 36px; }
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
