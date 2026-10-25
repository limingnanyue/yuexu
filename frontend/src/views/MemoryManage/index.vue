<template>
  <div class="yx-page memory-page">
    <PageHeader title="记忆库" description="留住对话中的事实、偏好与计划，让每一次回应都有迹可循。">
      <el-button :icon="Refresh" :loading="refreshing" @click="refreshAll">刷新</el-button>
      <el-button :icon="Setting" @click="openSettings">记忆设置</el-button>
      <el-dropdown trigger="click" @command="handleMaintenance">
        <el-button :icon="Tools" :loading="maintenanceLoading" :disabled="maintenanceLoading">
          维护<el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="task in maintenanceTasks" :key="task.action" :command="task.action" :disabled="maintenanceLoading">
              <span class="maintenance-item"><el-icon><component :is="task.icon" /></el-icon>{{ task.label }}</span>
            </el-dropdown-item>
            <el-dropdown-item command="reset" divided>批量重置记忆…</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button type="primary" :icon="Plus" :disabled="!accounts.length" @click="openCreate">新增记忆</el-button>
    </PageHeader>

    <el-alert v-if="accountsError" :title="accountsError" type="error" :closable="false" show-icon><el-button link type="primary" @click="refreshAll">重试加载记忆库</el-button></el-alert>

    <section class="memory-overview" aria-label="当前记忆库概况" v-loading="statsLoading">
      <div class="overview-heading">
        <div class="library-picker">
          <label class="query-label" for="memory-account">当前记忆库</label>
          <el-select id="memory-account" v-model="query.bot_id" placeholder="选择记忆库" filterable :loading="accountsLoading" aria-label="记忆库" @change="handleBotChange">
            <el-option v-for="account in accounts" :key="account.id" :label="accountLabel(account)" :value="account.id" />
          </el-select>
        </div>
        <span class="backend-status" role="status"><i aria-hidden="true" :class="{ degraded: stats?.backend === 'keyword', pending: !stats?.backend }"></i>{{ backendHint || stats?.backend || '检索状态不可用' }}</span>
      </div>
      <div class="memory-metrics">
        <div v-for="card in statCards" :key="card.label" class="memory-metric">
          <span class="metric-label"><el-icon><component :is="card.icon" /></el-icon>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
        </div>
      </div>
      <div class="overview-foot muted small">
        <span>当前库全部用户 · 对话摘要 {{ stats?.by_category?.conversation_summary ?? '—' }} 条</span>
        <span>{{ stats ? `模糊召回${stats.fuzzy_enabled ? '已开启' : '已关闭'}` : '召回状态 —' }} · 精确 {{ thresholdText(stats?.thresholds?.precise) }} / 模糊 {{ thresholdText(stats?.thresholds?.fuzzy) }}</span>
      </div>
    </section>

    <details class="memory-guide">
      <summary>记忆如何留存</summary>
      <div class="memory-guide-body">
        <p><strong>随对话提取</strong> · 记录明确的事实、偏好和计划，减少重复记忆。</p>
        <p><strong>静默后记笔记</strong> · 对话静默后按事件整理摘要；上下文过长时滚动压缩，保留原始对话。</p>
        <p><strong>管理与纠正</strong> · 点击内容查看全文；确认可提高可信度，屏蔽后不再参与召回。</p>
      </div>
    </details>

    <section class="yx-card memory-browser">
      <div class="yx-card-title">
        <h3>浏览记忆</h3>
        <span class="muted small">搜索全部用户的记忆，或指定一位对话用户。</span>
      </div>
      <form class="memory-filters" @submit.prevent="search">
        <div class="query-field keyword-field">
          <label class="query-label" for="memory-keyword">搜索内容</label>
          <el-input id="memory-keyword" v-model="query.keyword" :prefix-icon="Search" placeholder="搜索记忆内容或分类" clearable aria-label="关键词" />
        </div>
        <div class="query-field user-field">
          <label class="query-label" for="memory-user">用户 ID <span class="optional">可选</span></label>
          <el-input id="memory-user" v-model="query.user_id" placeholder="留空查看全部用户" clearable aria-label="用户 ID" />
        </div>
        <div class="query-actions">
          <el-button type="primary" native-type="submit" :icon="Search" :loading="loading">查询</el-button>
          <el-button @click="resetQuery">重置</el-button>
          <el-button class="filter-toggle" :aria-expanded="advancedFiltersOpen" aria-controls="memory-advanced-filters" @click="advancedFiltersOpen = !advancedFiltersOpen">更多筛选<span v-if="advancedFilterCount" class="filter-count">{{ advancedFilterCount }}</span><el-icon :class="{ 'is-expanded': advancedFiltersOpen }"><ArrowDown /></el-icon></el-button>
        </div>
        <div v-show="advancedFiltersOpen" id="memory-advanced-filters" class="advanced-filters">
        <div class="query-field">
          <label class="query-label" for="memory-scope">场景</label>
          <el-select id="memory-scope" v-model="query.scope_type" aria-label="场景范围">
            <el-option label="全部场景" value="all" /><el-option label="私聊" value="private" /><el-option label="群聊" value="group" /><el-option label="群共享" value="group_shared" /><el-option label="全局" value="global" />
          </el-select>
        </div>
        <div v-if="query.scope_type === 'group' || query.scope_type === 'group_shared'" class="query-field">
          <label class="query-label" for="memory-group">群号 <span class="optional">可选</span></label>
          <el-input id="memory-group" v-model="query.group_id" placeholder="全部群聊" clearable aria-label="群号筛选" />
        </div>
        <div class="query-field">
          <label class="query-label" for="memory-type">记忆类型</label>
          <el-select id="memory-type" v-model="query.memory_type" aria-label="记忆类型">
            <el-option label="全部类型" value="all" /><el-option label="事实" value="fact" /><el-option label="偏好" value="preference" /><el-option label="计划" value="plan" />
          </el-select>
        </div>
        <div class="query-field">
          <label class="query-label" for="memory-state">召回状态</label>
          <el-select id="memory-state" v-model="query.rejected" aria-label="屏蔽状态">
            <el-option label="全部状态" value="all" /><el-option label="正常" value="normal" /><el-option label="已屏蔽" value="rejected" />
          </el-select>
        </div>
        </div>
      </form>
    </section>

    <section class="yx-card memory-results" aria-label="记忆列表" :aria-busy="loading">
      <div class="yx-card-title results-heading">
        <div class="results-title"><h3>记忆列表</h3><span class="result-count">{{ total }} 条</span><span v-if="filtersDirty" class="muted small">筛选已更改，请查询</span></div>
        <el-button :icon="Download" :loading="exporting" :disabled="!query.bot_id || filtersDirty" @click="handleExport">导出筛选结果</el-button>
      </div>
      <div v-if="selectedRows.length" class="batch-bar">
        <span class="batch-summary">已选 <strong>{{ selectedRows.length }}</strong> 条</span>
        <div class="batch-actions">
          <el-button size="small" type="success" plain :loading="batchLoading === 'confirm'" :disabled="mutationBusy" @click="handleBatchConfirm">批量确认 / 恢复</el-button>
          <el-button size="small" type="warning" plain :loading="batchLoading === 'reject'" :disabled="mutationBusy" @click="handleBatchReject">批量屏蔽</el-button>
          <el-button size="small" type="danger" plain :loading="batchLoading === 'delete'" :disabled="mutationBusy" @click="handleBatchDelete">批量删除</el-button>
          <el-button link :disabled="mutationBusy" @click="clearSelection">取消选择</el-button>
        </div>
      </div>
      <div v-if="listError" class="list-error" role="alert"><span>{{ listError }}</span><el-button @click="loadList">重试</el-button></div>
      <template v-else>
        <el-table ref="tableRef" class="memory-table" v-loading="loading" :data="rows" row-key="id" @selection-change="handleSelectionChange">
          <el-table-column type="selection" width="44" :selectable="() => !mutationBusy" />
          <el-table-column label="记忆内容" min-width="340">
            <template #default="{ row }">
              <button type="button" class="memory-content" :class="{ 'is-rejected': row.rejected }" @click="openDetail(row)">{{ row.content || '（空内容）' }}</button>
              <div class="entry-tags"><el-tag size="small" effect="plain" :type="memoryTypeTagType(row.memory_type)">{{ memoryEntryLabel(row) }}</el-tag><el-tag v-if="row.rejected" size="small" type="danger" effect="plain">已屏蔽</el-tag><span v-for="tag in (row.tag_keywords || []).slice(0, 3)" :key="tag" class="keyword-tag">{{ tag }}</span></div>
            </template>
          </el-table-column>
          <el-table-column label="用户 / 场景" min-width="145">
            <template #default="{ row }"><span class="subject-id mono">{{ row.user_id || '—' }}</span><span class="entry-secondary">{{ sceneLabel(row) }}<template v-if="row.group_id"> · {{ row.group_id }}</template></span></template>
          </el-table-column>
          <el-table-column label="活跃程度" width="108"><template #default="{ row }"><span class="tier-marker" :class="row.tier">{{ tierLabel(row.tier) }}</span><span class="entry-secondary">热度 {{ formatHot(row.hot_score) }}</span></template></el-table-column>
          <el-table-column label="置信度" width="92"><template #default="{ row }"><span class="mono">{{ confidenceText(row.confidence) }}</span></template></el-table-column>
          <el-table-column label="最近更新" width="165"><template #default="{ row }"><span class="entry-time">{{ formatDateTime(row.updated_at || row.created_at) }}</span></template></el-table-column>
          <el-table-column label="操作" width="155" fixed="right">
            <template #default="{ row }"><div class="table-actions">
              <el-button link type="primary" :disabled="mutationBusy" @click="openEdit(row)">编辑</el-button>
              <el-button link type="success" :disabled="mutationBusy" :loading="isRowLoading(row.rejected ? 'restore' : 'confirm', row.id)" @click="confirmOne(row, row.rejected)">{{ row.rejected ? '恢复' : '确认' }}</el-button>
              <el-dropdown trigger="click" :disabled="mutationBusy" @command="command => handleRowCommand(command, row)"><el-button link :disabled="mutationBusy" :aria-label="`更多操作：${row.content}`"><el-icon><MoreFilled /></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="detail">查看详情</el-dropdown-item><el-dropdown-item v-if="!row.rejected" command="reject">屏蔽记忆</el-dropdown-item><el-dropdown-item command="delete" divided>删除记忆</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
            </div></template>
          </el-table-column>
          <template #empty><el-empty :description="emptyDescription" :image-size="72"><el-button v-if="query.bot_id && !filtersDirty" type="primary" plain @click="openCreate">新增第一条记忆</el-button></el-empty></template>
        </el-table>
        <div class="mobile-memories" v-loading="loading">
          <article v-for="row in rows" :key="row.id" class="mobile-memory">
            <div class="mobile-entry-heading"><el-checkbox :model-value="selectedRows.some(item => item.id === row.id)" :disabled="mutationBusy" :aria-label="`选择记忆：${row.content}`" @change="value => toggleMobileSelection(row, value)" /><span class="mono">{{ row.user_id || sceneLabel(row) }}</span><el-tag size="small" :type="memoryTypeTagType(row.memory_type)" effect="plain">{{ memoryEntryLabel(row) }}</el-tag><el-tag v-if="row.rejected" type="danger" size="small" effect="plain">已屏蔽</el-tag></div>
            <button type="button" class="memory-content" :class="{ 'is-rejected': row.rejected }" @click="openDetail(row)">{{ row.content }}</button>
            <div class="mobile-entry-meta"><span>{{ sceneLabel(row) }}<template v-if="row.group_id"> · {{ row.group_id }}</template></span><span class="tier-marker" :class="row.tier">{{ tierLabel(row.tier) }}</span><span>置信度 {{ confidenceText(row.confidence) }}</span></div>
            <div class="mobile-entry-footer"><span class="entry-time">{{ formatDateTime(row.updated_at || row.created_at) }}</span><div><el-button size="small" :disabled="mutationBusy" @click="openDetail(row)">详情</el-button><el-button size="small" type="primary" plain :disabled="mutationBusy" @click="openEdit(row)">编辑</el-button></div></div>
          </article>
          <el-empty v-if="!rows.length" :description="emptyDescription" :image-size="64" />
        </div>
      </template>
      <div v-if="total > 0" class="memory-pagination"><span class="muted small">每页</span><el-select :model-value="pageSize" aria-label="每页条数" @change="handleSizeChange"><el-option v-for="size in [10,20,50,100]" :key="size" :label="`${size} 条`" :value="size" /></el-select><el-pagination :current-page="page" :page-size="pageSize" :total="total" :pager-count="5" layout="prev, pager, next" @current-change="handlePageChange" /></div>
    </section>

    <el-drawer v-model="detailVisible" title="记忆详情" size="min(540px, 100vw)" class="memory-detail">
      <template v-if="detailEntry">
        <div class="detail-tags"><el-tag :type="memoryTypeTagType(detailEntry.memory_type)" effect="plain">{{ memoryEntryLabel(detailEntry) }}</el-tag><el-tag :type="tierTagType(detailEntry.tier)" effect="plain">{{ tierLabel(detailEntry.tier) }}</el-tag><el-tag v-if="detailEntry.rejected" type="danger" effect="plain">已屏蔽 · 不参与召回</el-tag></div>
        <p v-if="detailEntry.category === 'conversation_summary'" class="summary-intro muted small">由对话分段整理的历史笔记，完整对话仍保留在上下文中。</p>
        <p class="detail-content">{{ detailEntry.content }}</p>
        <div class="detail-keywords"><span v-for="tag in detailEntry.tag_keywords || []" :key="tag" class="keyword-tag">{{ tag }}</span></div>
        <dl class="detail-fields">
          <div><dt>所属记忆库</dt><dd>{{ accountLabel(accounts.find(a => a.id === detailEntry.bot_id)) || detailEntry.bot_id }}</dd></div>
          <div><dt>用户 ID</dt><dd class="mono">{{ detailEntry.user_id }}</dd></div>
          <div><dt>对话场景</dt><dd>{{ sceneLabel(detailEntry) }}<template v-if="detailEntry.group_id"> · {{ detailEntry.group_id }}</template></dd></div>
          <div><dt>内容分类</dt><dd>{{ detailEntry.category === 'conversation_summary' ? '对话摘要' : detailEntry.category || '—' }}</dd></div>
          <div><dt>置信度</dt><dd>{{ confidenceText(detailEntry.confidence) }}</dd></div>
          <div><dt>热度 / 召回次数</dt><dd>{{ formatHot(detailEntry.hot_score) }} / {{ detailEntry.hit_count ?? 0 }} 次</dd></div>
          <div><dt>创建时间</dt><dd>{{ formatDateTime(detailEntry.created_at) }}</dd></div>
          <div><dt>更新时间</dt><dd>{{ formatDateTime(detailEntry.updated_at || detailEntry.created_at) }}</dd></div>
          <div><dt>最近召回</dt><dd>{{ detailEntry.last_hit_at ? formatDateTime(detailEntry.last_hit_at) : '尚未召回' }}</dd></div>
          <div><dt>来源消息</dt><dd class="mono">{{ detailEntry.source_message_id || '无来源消息' }}</dd></div>
        </dl>
        <p class="muted small detail-id">记忆 ID · {{ detailEntry.id }}</p>
      </template>
      <template #footer><div v-if="detailEntry" class="detail-actions"><el-button type="danger" plain :disabled="mutationBusy" @click="handleDelete(detailEntry)">删除</el-button><el-button v-if="!detailEntry.rejected" type="warning" plain :disabled="mutationBusy" @click="handleReject(detailEntry)">屏蔽</el-button><el-button type="success" plain :disabled="mutationBusy" @click="confirmOne(detailEntry, detailEntry.rejected)">{{ detailEntry.rejected ? '恢复召回' : '确认记忆' }}</el-button><el-button type="primary" :disabled="mutationBusy" @click="openEdit(detailEntry)">编辑</el-button></div></template>
    </el-drawer>

    <el-dialog v-model="editorVisible" :title="editingId ? '编辑记忆' : '新增记忆'" width="min(600px, calc(100vw - 32px))" :close-on-click-modal="false" :close-on-press-escape="!editorSaving" :show-close="!editorSaving">
      <p class="editor-intro muted">{{ editingId ? '更正内容、类型和关键词；所属记忆库、用户与召回状态保持原样。' : '补充一条明确的事实、偏好或计划，保存后纳入现有记忆检索。' }}</p>
      <el-form label-position="top" :disabled="editorSaving" @submit.prevent="saveEntry">
        <div class="editor-grid">
          <el-form-item label="记忆库" required><el-select v-model="editorForm.bot_id" aria-label="新增记忆所属记忆库" :disabled="!!editingId" filterable><el-option v-for="account in accounts" :key="account.id" :label="accountLabel(account)" :value="account.id" /></el-select></el-form-item>
          <el-form-item v-if="['private', 'group'].includes(editorForm.scope_type)" label="用户 ID" required><el-input v-model="editorForm.user_id" aria-label="记忆所属用户" :disabled="!!editingId" maxlength="64" placeholder="填写对话用户 ID" /></el-form-item>
          <el-form-item label="场景" required><el-select v-model="editorForm.scope_type" aria-label="记忆场景" :disabled="!!editingId"><el-option label="私聊（仅该用户的私聊可见）" value="private" /><el-option label="群聊（仅该用户在该群可见）" value="group" /><el-option label="群共享（该群所有成员可见）" value="group_shared" /><el-option label="全局（机器人全部会话可见）" value="global" /></el-select></el-form-item>
          <el-form-item v-if="['group', 'group_shared'].includes(editorForm.scope_type)" label="群号" required><el-input v-model="editorForm.group_id" aria-label="记忆所属群号" :disabled="!!editingId" maxlength="64" placeholder="填写群号" /></el-form-item>
          <el-form-item label="记忆类型"><el-select v-model="editorForm.memory_type" aria-label="编辑记忆类型"><el-option label="事实" value="fact" /><el-option label="偏好" value="preference" /><el-option label="计划" value="plan" /></el-select></el-form-item>
        </div>
        <el-form-item label="记忆内容" required><el-input v-model="editorForm.content" type="textarea" :autosize="{minRows: 5, maxRows: 12}" aria-label="记忆内容" placeholder="例如：用户喜欢绿茶，不喜欢太甜的饮品。" /></el-form-item>
        <el-form-item label="关键词（可选）"><el-input v-model="editorForm.tag_keywords" aria-label="记忆关键词" placeholder="使用逗号分隔，例如：绿茶，饮品" /><span class="muted small">留空时，新建记忆自动提取关键词。</span></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="editorSaving" @click="editorVisible = false">取消</el-button><el-button type="primary" :loading="editorSaving" @click="saveEntry">{{ editingId ? '保存更正' : '保存记忆' }}</el-button></template>
    </el-dialog>

    <el-dialog
      v-model="resetVisible"
      title="批量重置记忆"
      width="min(460px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="记忆库" required>
          <el-select
            v-model="resetForm.bot_id"
            placeholder="请选择记忆库"
            style="width: 100%"
          >
            <el-option
              v-for="account in accounts"
              :key="account.id"
              :label="accountLabel(account)"
              :value="account.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="场景范围">
          <el-select v-model="resetForm.scope_type" style="width: 100%">
            <el-option label="全部场景" value="all" />
            <el-option label="仅私聊" value="private" />
            <el-option label="仅群聊" value="group" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="resetForm.scope_type !== 'private'" label="群号（可选）">
          <el-input
            v-model="resetForm.group_id"
            placeholder="留空表示不限制群号"
            clearable
          />
        </el-form-item>
      </el-form>
      <div class="yx-hint">
        将删除所选记忆库与场景范围内所有用户的长期记忆及向量索引，不受列表的用户或关键词筛选限制。共用此库的连接都会受影响，操作不可恢复。
      </div>
      <template #footer>
        <el-button :disabled="resetting" @click="resetVisible = false">取消</el-button>
        <el-button type="danger" :loading="resetting" @click="confirmReset">
          确认重置
        </el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="settingsVisible"
      title="记忆设置"
      direction="rtl"
      size="min(520px, 100vw)"
      :close-on-click-modal="false"
    >
      <div v-loading="settingsLoading" class="settings-body">
        <div class="yx-hint">
          精准模式只检索热记忆与温记忆；模糊模式在模糊阈值放宽后可访问冷记忆。阈值越低召回越宽，但噪声也会增加。
        </div>

        <div v-if="!settingsLoading && !settingsLoaded" class="settings-load-error" role="alert">
          <span>参数加载失败，暂时无法保存。</span>
          <el-button link type="primary" @click="loadSettings">重新加载</el-button>
        </div>

        <el-form
          :model="settingsForm"
          label-position="top"
          :disabled="!settingsLoaded"
          class="settings-form"
        >
          <section class="settings-section">
            <div class="settings-section-title">
              <h4>双模式召回</h4>
              <span class="muted small">精准模式偏保守，模糊模式覆盖更久远的记忆</span>
            </div>
            <div class="settings-grid">
              <el-form-item label="模糊记忆开关">
                <div class="switch-line">
                  <el-switch
                    v-model="settingsForm.fuzzy_enabled"
                    aria-label="模糊记忆开关"
                  />
                  <span class="muted small">允许模糊问句召回</span>
                </div>
              </el-form-item>
              <el-form-item label="自动识别确认/否认">
                <div class="switch-line">
                  <el-switch
                    v-model="settingsForm.feedback_auto"
                    aria-label="自动识别确认或否认"
                  />
                  <span class="muted small">自动识别上一轮反馈</span>
                </div>
              </el-form-item>
              <el-form-item label="精确阈值">
                <el-input-number
                  v-model="settingsForm.precise_threshold"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :precision="2"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="模糊阈值">
                <el-input-number
                  v-model="settingsForm.fuzzy_threshold"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :precision="2"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="召回条数 top_k">
                <el-input-number
                  v-model="settingsForm.top_k"
                  :min="1"
                  :max="50"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="Prompt 字符预算">
                <el-input-number
                  v-model="settingsForm.max_prompt_chars"
                  :min="100"
                  :max="10000"
                  :step="50"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="多级重排">
                <div class="switch-line">
                  <el-switch
                    v-model="settingsForm.rerank_enabled"
                    aria-label="多级重排"
                  />
                  <span class="muted small">综合热度与置信度</span>
                </div>
              </el-form-item>
            </div>
          </section>

          <section class="settings-section">
            <div class="settings-section-title">
              <h4>语义向量</h4>
              <span class="muted small">中文语义检索核心，切换后重启并自动重建索引</span>
            </div>
            <div class="settings-grid">
              <el-form-item label="向量方案">
                <el-select v-model="settingsForm.embedding.provider" style="width: 100%">
                  <el-option label="内置零依赖（默认）" value="builtin" />
                  <el-option label="本地 ONNX 中文模型" value="onnx" />
                  <el-option label="OpenAI 兼容接口" value="api" />
                </el-select>
              </el-form-item>
              <el-form-item v-if="settingsForm.embedding.provider === 'builtin'" label="向量维度">
                <el-input-number
                  v-model="settingsForm.embedding.dim"
                  :min="64"
                  :max="2048"
                  :step="64"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item
                v-if="settingsForm.embedding.provider === 'onnx'"
                label="模型目录"
                class="span-2"
              >
                <el-input
                  v-model="settingsForm.embedding.model_path"
                  placeholder="相对项目根，需包含 model.onnx 与 vocab.txt"
                />
              </el-form-item>
              <el-form-item
                v-if="settingsForm.embedding.provider === 'api'"
                label="接口地址"
                class="span-2"
              >
                <el-input
                  v-model="settingsForm.embedding.api_base_url"
                  placeholder="例如 https://api.siliconflow.cn/v1"
                />
              </el-form-item>
              <el-form-item
                v-if="settingsForm.embedding.provider === 'api'"
                label="接口模型"
              >
                <el-input
                  v-model="settingsForm.embedding.api_model"
                  placeholder="例如 BAAI/bge-large-zh-v1.5"
                />
              </el-form-item>
              <el-form-item
                v-if="settingsForm.embedding.provider === 'api'"
                label="API Key"
              >
                <el-input
                  v-model="settingsForm.embedding.api_key"
                  placeholder="留空表示沿用已保存密钥"
                  show-password
                />
              </el-form-item>
            </div>
          </section>

          <section class="settings-section">
            <div class="settings-section-title">
              <h4>缓存与索引</h4>
              <span class="muted small">影响召回延迟与向量检索范围</span>
            </div>
            <div class="settings-grid">
              <el-form-item label="召回缓存 TTL（秒）">
                <el-input-number
                  v-model="settingsForm.recall_cache_ttl"
                  :min="0"
                  :max="86400"
                  :step="30"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="HNSW search_ef">
                <el-input-number
                  v-model="settingsForm.hnsw_search_ef"
                  :min="8"
                  :max="512"
                  :step="8"
                  controls-position="right"
                />
              </el-form-item>
            </div>
          </section>

          <section class="settings-section">
            <div class="settings-section-title">
              <h4>冷热分层与写入</h4>
              <span class="muted small">控制分层边界、自动提取与冷记忆清理</span>
            </div>
            <div class="settings-grid">
              <el-form-item label="热记忆天数">
                <el-input-number
                  v-model="settingsForm.hot_days"
                  :min="1"
                  :max="365"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="温记忆天数">
                <el-input-number
                  v-model="settingsForm.warm_days"
                  :min="1"
                  :max="3650"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="LLM 抽取记忆">
                <div class="switch-line">
                  <el-switch
                    v-model="settingsForm.llm_extract"
                    aria-label="LLM 抽取记忆"
                  />
                  <span class="muted small">提取结构化事实</span>
                </div>
              </el-form-item>
              <el-form-item label="异步写入">
                <div class="switch-line">
                  <el-switch
                    v-model="settingsForm.write_async"
                    aria-label="异步写入记忆"
                  />
                  <span class="muted small">减少回复等待</span>
                </div>
              </el-form-item>
              <el-form-item label="自动清理冷记忆">
                <div class="switch-line">
                  <el-switch
                    v-model="settingsForm.auto_purge_cold"
                    aria-label="自动清理冷记忆"
                  />
                  <span class="muted small">按保留天数清理</span>
                </div>
              </el-form-item>
              <el-form-item label="冷记忆保留天数">
                <el-input-number
                  v-model="settingsForm.cold_purge_days"
                  :min="1"
                  :max="3650"
                  controls-position="right"
                />
              </el-form-item>
            </div>
          </section>
        </el-form>
      </div>

      <template #footer>
        <div class="drawer-footer">
          <span class="muted small">部分参数下一轮对话生效</span>
          <div class="drawer-footer-actions">
            <el-button :disabled="settingsSaving" @click="settingsVisible = false">
              取消
            </el-button>
            <el-button
              type="primary"
              :loading="settingsSaving"
              :disabled="!settingsLoaded"
              @click="saveSettings"
            >
              保存设置
            </el-button>
          </div>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  Download,
  MoreFilled,
  Plus,
  Refresh,
  Search,
  Setting,
  Tools,
} from '@element-plus/icons-vue'

import PageHeader from '@/components/PageHeader.vue'
import { listMemoryLibraries } from '@/api/account'
import {
  confirmMemories,
  createMemory,
  deleteMemory,
  exportMemory,
  getMemorySettings,
  listMemories,
  memoryStats,
  rejectMemories,
  resetMemory,
  runMemoryMaintenance,
  updateMemorySettings,
  updateMemory,
} from '@/api/memory'
import { formatDateTime, truncate } from '@/utils/format'

const EMBEDDING_DEFAULTS = Object.freeze({
  provider: 'builtin',
  dim: 512,
  model_path: '',
  api_base_url: '',
  api_model: '',
  api_key: '',
})

const SETTINGS_DEFAULTS = Object.freeze({
  fuzzy_enabled: true,
  feedback_auto: true,
  precise_threshold: 0.7,
  fuzzy_threshold: 0.5,
  top_k: 5,
  max_prompt_chars: 900,
  recall_cache_ttl: 600,
  hot_days: 7,
  warm_days: 30,
  hnsw_search_ef: 48,
  rerank_enabled: true,
  llm_extract: true,
  write_async: true,
  auto_purge_cold: false,
  cold_purge_days: 180,
  embedding: { ...EMBEDDING_DEFAULTS },
})

const NUMERIC_SETTING_KEYS = Object.freeze([
  'precise_threshold',
  'fuzzy_threshold',
  'top_k',
  'max_prompt_chars',
  'recall_cache_ttl',
  'hot_days',
  'warm_days',
  'hnsw_search_ef',
  'cold_purge_days',
])

const maintenanceTasks = [
  {
    action: 'decay',
    label: '热度衰减',
    icon: 'TrendCharts',
    confirm: '将按当前衰减系数降低所有记忆的热度，是否继续？',
  },
  {
    action: 'dedupe',
    label: '自动去重',
    icon: 'CopyDocument',
    confirm: '将扫描相似记忆并删除重复项，是否继续？',
  },
  {
    action: 'purge',
    label: '冷记忆清理',
    icon: 'Delete',
    confirm: '将立即清理超过保留天数且热度偏低的冷记忆，是否继续？',
  },
  {
    action: 'gc',
    label: '向量 GC',
    icon: 'Brush',
    confirm: '将清理向量库中已无对应记忆的孤儿向量，是否继续？',
  },
  {
    action: 'reindex',
    label: '重建索引',
    icon: 'RefreshRight',
    confirm:
      '重建索引会重新写入全部记忆，数据量大时可能耗时较长，期间检索结果可能不完整。是否继续？',
  },
]

const accounts = ref([])
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const accountsLoading = ref(false)
const accountsError = ref('')
const refreshing = ref(false)
const statsLoading = ref(false)
const stats = ref(null)
const selectedRows = ref([])
const tableRef = ref()
const actionLoading = ref('')
const batchLoading = ref('')
const exporting = ref(false)
const listError = ref('')
const loadedQueryKey = ref('')
const detailVisible = ref(false)
const detailEntry = ref(null)
const editorVisible = ref(false)
const editorSaving = ref(false)
const editingId = ref('')
const editorForm = reactive({
  bot_id: '', user_id: '', scope_type: 'private', group_id: '',
  content: '', memory_type: 'fact', tag_keywords: '',
})
const mutationBusy = computed(() => !!(actionLoading.value || batchLoading.value || editorSaving.value))

const resetVisible = ref(false)
const resetting = ref(false)
const resetForm = reactive({
  bot_id: '',
  scope_type: 'all',
  group_id: '',
})

const settingsVisible = ref(false)
const settingsLoading = ref(false)
const settingsSaving = ref(false)
const settingsLoaded = ref(false)
const settingsForm = reactive({ ...SETTINGS_DEFAULTS })

const maintenanceLoading = ref(false)
const advancedFiltersOpen = ref(false)

const query = reactive({
  bot_id: '',
  user_id: '',
  scope_type: 'all',
  memory_type: 'all',
  rejected: 'all',
  keyword: '',
  group_id: '',
})
const advancedFilterCount = computed(() => [
  query.scope_type !== 'all',
  ['group', 'group_shared'].includes(query.scope_type) && !!query.group_id.trim(),
  query.memory_type !== 'all',
  query.rejected !== 'all',
].filter(Boolean).length)

let listRequestId = 0
let statsRequestId = 0
const filtersDirty = computed(() => loadedQueryKey.value !== JSON.stringify(memoryFilters()))
const emptyDescription = computed(() => {
  if (!query.bot_id) return '请先添加连接以创建记忆库，或选择已保留的记忆库'
  if (filtersDirty.value) return '点击「查询」查看当前筛选范围的记忆'
  return '当前范围暂无记忆，可调整筛选或补充一条记忆'
})

function memoryFilters() {
  const params = { bot_id: query.bot_id, library_id: query.bot_id }
  if (query.user_id.trim()) params.user_id = query.user_id.trim()
  if (query.scope_type === 'group_shared') {
    params.target_type = 'group'
  } else if (query.scope_type === 'global') {
    params.scope_type = 'global'
  } else if (query.scope_type !== 'all') {
    params.scope_type = query.scope_type
  }
  if ((query.scope_type === 'group' || query.scope_type === 'group_shared') && query.group_id.trim()) {
    params.group_id = query.group_id.trim()
  }
  if (query.memory_type !== 'all') params.memory_type = query.memory_type
  if (query.rejected !== 'all') params.rejected = query.rejected === 'rejected'
  if (query.keyword.trim()) params.keyword = query.keyword.trim()
  return params
}

function openDetail(row) {
  detailEntry.value = row
  detailVisible.value = true
}

function openCreate() {
  editingId.value = ''
  Object.assign(editorForm, {
    bot_id: query.bot_id || accounts.value[0]?.id || '',
    user_id: query.scope_type === 'group_shared' || query.scope_type === 'global' ? '' : query.user_id.trim(),
    scope_type: ['group', 'group_shared', 'global'].includes(query.scope_type) ? query.scope_type : 'private',
    group_id: query.group_id.trim(),
    content: '', memory_type: query.memory_type === 'all' ? 'fact' : query.memory_type, tag_keywords: '',
  })
  editorVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(editorForm, {
    bot_id: row.bot_id, user_id: row.user_id, scope_type: row.scope_type || 'private',
    group_id: row.group_id || '', content: row.content || '', memory_type: row.memory_type || 'fact',
    tag_keywords: (row.tag_keywords || []).join('，'),
  })
  editorVisible.value = true
}

async function saveEntry() {
  if (editorSaving.value) return
  const content = editorForm.content.trim()
  if (!content) return ElMessage.warning('请填写记忆内容')
  if (!editingId.value && !editorForm.bot_id) {
    return ElMessage.warning('请选择记忆库')
  }
  const scope = editorForm.scope_type
  if (!editingId.value && ['private', 'group'].includes(scope) && !editorForm.user_id.trim()) {
    return ElMessage.warning('私聊 / 群聊记忆需要填写用户 ID')
  }
  if (!editingId.value && ['group', 'group_shared'].includes(scope) && !editorForm.group_id.trim()) {
    return ElMessage.warning('群聊 / 群共享记忆需要填写群号')
  }
  const payload = {
    content, memory_type: editorForm.memory_type,
    tag_keywords: [...new Set(editorForm.tag_keywords.split(/[,，、\n]/).map(tag => tag.trim()).filter(Boolean))],
  }
  editorSaving.value = true
  try {
    if (editingId.value) {
      await updateMemory(editingId.value, payload)
    } else {
      await createMemory({
        ...payload, bot_id: editorForm.bot_id, library_id: editorForm.bot_id,
        user_id: ['private', 'group'].includes(scope) ? editorForm.user_id.trim() : '',
        scope_type: scope,
        ...(['group', 'group_shared'].includes(scope) ? { group_id: editorForm.group_id.trim() } : {}),
      })
    }
    editorVisible.value = false
    detailVisible.value = false
    ElMessage.success(editingId.value ? '记忆已更正' : '记忆已新增')
    await refreshAfterMutation()
  } catch {
    // 请求拦截器显示具体原因，保留表单供修正或重试。
  } finally {
    editorSaving.value = false
  }
}

function handleRowCommand(command, row) {
  if (command === 'detail') openDetail(row)
  if (command === 'reject') handleReject(row)
  if (command === 'delete') handleDelete(row)
}

function toggleMobileSelection(row, selected) {
  tableRef.value?.toggleRowSelection(row, selected)
}

const statCards = computed(() => [
  { label: '记忆总数', value: stats.value?.total ?? '—', icon: 'Collection' },
  { label: '热记忆', value: stats.value?.tiers?.hot ?? '—', icon: 'Sunny' },
  { label: '温记忆', value: stats.value?.tiers?.warm ?? '—', icon: 'Cloudy' },
  { label: '冷记忆', value: stats.value?.tiers?.cold ?? '—', icon: 'Moon' },
  { label: '已屏蔽', value: stats.value?.rejected ?? '—', icon: 'CircleClose' },
])

const backendHint = computed(() => {
  if (stats.value?.backend === 'chroma') return '向量检索'
  if (stats.value?.backend === 'builtin') return '本地语义检索'
  if (stats.value?.backend === 'keyword') return '关键词降级'
  return ''
})

function accountLabel(account) {
  if (!account) return ''
  return `${account.name || account.id} · ${account.memory_count ?? 0} 条 · ${account.account_count ? `${account.account_count} 个连接` : '已保留'}`
}

function thresholdText(value) {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(2) : '—'
}

function memoryTypeLabel(type) {
  return { fact: '事实', preference: '偏好', plan: '计划' }[type] || type || '—'
}

function memoryEntryLabel(row) {
  return row.category === 'conversation_summary' ? '对话摘要' : memoryTypeLabel(row.memory_type)
}

function memoryTypeTagType(type) {
  return { fact: 'info', preference: 'warning', plan: 'success' }[type] || 'info'
}

function tierLabel(tier) {
  return { hot: '热记忆', warm: '温记忆', cold: '冷记忆' }[tier] || tier || '—'
}

function tierTagType(tier) {
  return { hot: 'danger', warm: 'warning', cold: 'info' }[tier] || 'info'
}

function sceneLabel(row) {
  if (row.target_type === 'group') return '群共享'
  if (row.target_type === 'global' || row.scope_type === 'global') return '全局'
  return row.scope_type === 'group' || row.group_id ? '群聊' : '私聊'
}

function formatHot(value) {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(1) : '—'
}

function normalizeConfidence(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.min(1, Math.max(0, numeric))
}

function confidencePercent(value) {
  return Math.round(normalizeConfidence(value) * 100)
}

function confidenceText(value) {
  return `${confidencePercent(value)}%`
}

function actionKey(action, id) {
  return `${action}:${id}`
}

function isRowLoading(action, id) {
  return actionLoading.value === actionKey(action, id)
}

function clearSelection() {
  selectedRows.value = []
  tableRef.value?.clearSelection()
}

function handleSelectionChange(selection) {
  selectedRows.value = selection
}

function clearTable() {
  rows.value = []
  total.value = 0
  clearSelection()
}

async function loadAccounts() {
  accountsLoading.value = true
  accountsError.value = ''
  try {
    const data = await listMemoryLibraries()
    accounts.value = Array.isArray(data) ? data : data?.items || []
  } catch {
    accountsError.value = '记忆库列表加载失败，已保留当前选择，请重试。'
    return
  } finally {
    accountsLoading.value = false
  }

  if (!query.bot_id && accounts.value.length) {
    query.bot_id = accounts.value[0].id
  } else if (
    query.bot_id &&
    !accounts.value.some((account) => account.id === query.bot_id)
  ) {
    query.bot_id = accounts.value[0]?.id || ''
  }
}

async function loadStats() {
  const requestId = ++statsRequestId
  statsLoading.value = true
  try {
    const data = await memoryStats(query.bot_id ? { bot_id: query.bot_id, library_id: query.bot_id } : {})
    if (requestId !== statsRequestId) return
    stats.value = data
  } catch {
    if (requestId === statsRequestId) stats.value = null
  } finally {
    if (requestId === statsRequestId) statsLoading.value = false
  }
}

async function loadList() {
  const requestId = ++listRequestId
  const filters = memoryFilters()
  const queryKey = JSON.stringify(filters)
  listError.value = ''
  clearSelection()

  if (!query.bot_id) {
    rows.value = []
    total.value = 0
    loading.value = false
    clearSelection()
    return
  }

  loading.value = true
  try {
    const params = {
      ...filters,
      page: page.value,
      page_size: pageSize.value,
    }
    const data = await listMemories(params)
    if (requestId !== listRequestId || queryKey !== JSON.stringify(memoryFilters())) return
    const nextTotal = Number(data?.total) || 0
    const lastPage = Math.max(1, Math.ceil(nextTotal / pageSize.value))
    if (page.value > lastPage) {
      page.value = lastPage
      await loadList()
      return
    }
    rows.value = data?.items || []
    total.value = nextTotal
    loadedQueryKey.value = queryKey
  } catch {
    if (requestId !== listRequestId) return
    rows.value = []
    total.value = 0
    listError.value = '记忆加载失败，请检查服务连接后重试。'
  } finally {
    if (requestId === listRequestId) loading.value = false
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await loadAccounts()
    await Promise.all([loadStats(), loadList()])
  } finally {
    refreshing.value = false
  }
}

async function search() {
  if (!query.bot_id) {
    clearTable()
    ElMessage.warning('请先选择记忆库')
    return
  }
  page.value = 1
  clearSelection()
  await loadList()
}

async function resetQuery() {
  query.user_id = ''
  query.scope_type = 'all'
  query.memory_type = 'all'
  query.rejected = 'all'
  query.keyword = ''
  query.group_id = ''
  page.value = 1
  await loadList()
}

async function handleBotChange() {
  page.value = 1
  clearTable()
  await Promise.all([
    loadStats(),
    loadList(),
  ])
}

function handlePageChange(nextPage) {
  clearSelection()
  page.value = nextPage
  loadList()
}

function handleSizeChange(nextSize) {
  clearSelection()
  pageSize.value = nextSize
  page.value = 1
  loadList()
}

async function refreshAfterMutation({ shrink = false } = {}) {
  detailVisible.value = false
  clearSelection()
  if (shrink && page.value > 1) page.value -= 1
  await Promise.all([loadList(), loadStats()])
}

async function confirmOne(row, restore = false) {
  if (mutationBusy.value) return
  const action = restore ? 'restore' : 'confirm'
  const key = actionKey(action, row.id)
  actionLoading.value = key
  try {
    await confirmMemories([row.id])
    ElMessage.success(restore ? '已恢复该记忆，重新参与召回' : '已确认该记忆')
    await refreshAfterMutation({
      shrink: restore && query.rejected === 'rejected' && rows.value.length === 1,
    })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    if (actionLoading.value === key) actionLoading.value = ''
  }
}

function contentHint(row) {
  return row.content ? `「${truncate(row.content, 36)}」` : '该记忆'
}

async function handleReject(row) {
  try {
    await ElMessageBox.confirm(
      `屏蔽${contentHint(row)}后将降低热度并停止参与召回，之后可恢复。确定继续吗？`,
      '屏蔽记忆',
      {
        type: 'warning',
        confirmButtonText: '屏蔽',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  const key = actionKey('reject', row.id)
  actionLoading.value = key
  try {
    await rejectMemories([row.id])
    ElMessage.success('已屏蔽该记忆，可从详情中恢复')
    await refreshAfterMutation({ shrink: rows.value.length === 1 })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    if (actionLoading.value === key) actionLoading.value = ''
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `删除${contentHint(row)}后将无法恢复，确定继续吗？`,
      '删除记忆',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  const key = actionKey('delete', row.id)
  actionLoading.value = key
  try {
    await deleteMemory(row.id)
    ElMessage.success('已删除该记忆')
    await refreshAfterMutation({ shrink: rows.value.length === 1 })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    if (actionLoading.value === key) actionLoading.value = ''
  }
}

async function handleBatchConfirm() {
  const ids = selectedRows.value.map((row) => row.id)
  if (!ids.length) return

  const shrink =
    query.rejected === 'rejected' &&
    ids.length >= rows.value.length &&
    page.value > 1

  batchLoading.value = 'confirm'
  try {
    await confirmMemories(ids)
    ElMessage.success(`已确认 ${ids.length} 条记忆`)
    await refreshAfterMutation({ shrink })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    batchLoading.value = ''
  }
}

async function handleBatchReject() {
  const ids = selectedRows.value.map((row) => row.id)
  if (!ids.length) return

  try {
    await ElMessageBox.confirm(
      `选中的 ${ids.length} 条记忆将停止参与召回，之后可恢复。确定继续吗？`,
      '批量屏蔽',
      {
        type: 'warning',
        confirmButtonText: '批量屏蔽',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  batchLoading.value = 'reject'
  try {
    await rejectMemories(ids)
    ElMessage.success(`已否认并屏蔽 ${ids.length} 条记忆`)
    await refreshAfterMutation({
      shrink:
        query.rejected === 'normal' &&
        ids.length >= rows.value.length &&
        page.value > 1,
    })
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    batchLoading.value = ''
  }
}

async function handleBatchDelete() {
  const ids = selectedRows.value.map((row) => row.id)
  if (!ids.length) return

  try {
    await ElMessageBox.confirm(
      `将逐条删除选中的 ${ids.length} 条记忆，删除后无法恢复，确定继续吗？`,
      '批量删除记忆',
      {
        type: 'warning',
        confirmButtonText: '批量删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  batchLoading.value = 'delete'
  let deleted = 0
  let failed = 0
  try {
    for (const id of ids) {
      try {
        await deleteMemory(id)
        deleted += 1
      } catch {
        failed += 1
      }
    }

    if (deleted > 0) {
      ElMessage.success(
        failed > 0 ? `已删除 ${deleted} 条，另有 ${failed} 条失败` : `已删除 ${deleted} 条记忆`,
      )
    } else if (failed > 0) {
      ElMessage.warning('批量删除失败，请稍后重试')
    }

    await refreshAfterMutation({
      shrink: deleted >= rows.value.length && page.value > 1,
    })
  } finally {
    batchLoading.value = ''
  }
}

async function handleMaintenance(action) {
  if (action === 'reset') return openReset()
  const task = maintenanceTasks.find((item) => item.action === action)
  if (!task) return

  try {
    await ElMessageBox.confirm(task.confirm, task.label, {
      type: 'warning',
      confirmButtonText: action === 'reindex' ? '开始重建' : '执行',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  maintenanceLoading.value = true
  try {
    const data = await runMemoryMaintenance(action)
    const affected = data?.affected ?? 0
    ElMessage.success(`${data?.message || '执行完成'}，影响 ${affected} 条`)
    page.value = 1
    clearSelection()
    await Promise.all([loadList(), loadStats()])
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    maintenanceLoading.value = false
  }
}

function openReset() {
  resetForm.bot_id = query.bot_id || accounts.value[0]?.id || ''
  resetForm.scope_type = ['private', 'group'].includes(query.scope_type)
    ? query.scope_type
    : 'all'
  resetForm.group_id = query.scope_type === 'group' ? query.group_id.trim() : ''
  resetVisible.value = true
}

async function confirmReset() {
  if (!resetForm.bot_id) {
    ElMessage.warning('请选择记忆库')
    return
  }

  resetting.value = true
  try {
    const data = await resetMemory({
      bot_id: resetForm.bot_id, library_id: resetForm.bot_id,
      scope_type: resetForm.scope_type === 'all' ? null : resetForm.scope_type,
      group_id: resetForm.scope_type !== 'private' ? resetForm.group_id.trim() || null : null,
    })
    ElMessage.success(`已删除 ${data?.deleted ?? 0} 条记忆`)
    resetVisible.value = false
    page.value = 1
    clearSelection()
    await Promise.all([loadList(), loadStats()])
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    resetting.value = false
  }
}

function filenameSafe(value) {
  return String(value || '').replace(/[\\/:*?"<>|\s]+/g, '_')
}

async function handleExport() {
  if (!query.bot_id) {
    ElMessage.warning('请先选择记忆库')
    return
  }

  exporting.value = true
  const filters = memoryFilters()
  try {
    const data = await exportMemory(filters)
    const list = Array.isArray(data) ? data : []
    const blob = new Blob([JSON.stringify(list, null, 2)], {
      type: 'application/json;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `yuexu-memory-${filenameSafe(filters.bot_id)}-${filenameSafe(
      filters.user_id || 'all',
    )}-${Date.now()}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success(`已导出 ${list.length} 条记忆`)
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    exporting.value = false
  }
}

function normalizeBoolean(value, fallback) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'on'].includes(normalized)) return true
    if (['false', '0', 'no', 'off', ''].includes(normalized)) return false
  }
  return fallback
}

function normalizeNumber(value, fallback) {
  if (value === null || value === undefined || value === '') return fallback
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

function applySettings(data) {
  for (const [key, fallback] of Object.entries(SETTINGS_DEFAULTS)) {
    if (key === 'embedding') continue
    if (typeof fallback === 'boolean') {
      settingsForm[key] = normalizeBoolean(data?.[key], fallback)
    } else {
      settingsForm[key] = normalizeNumber(data?.[key], fallback)
    }
  }
  const embedding = data?.embedding || {}
  settingsForm.embedding = {
    ...EMBEDDING_DEFAULTS,
    provider: ['builtin', 'onnx', 'api'].includes(embedding.provider)
      ? embedding.provider
      : 'builtin',
    dim: normalizeNumber(embedding.dim, EMBEDDING_DEFAULTS.dim),
    model_path: embedding.model_path || EMBEDDING_DEFAULTS.model_path,
    api_base_url: embedding.api_base_url || EMBEDDING_DEFAULTS.api_base_url,
    api_model: embedding.api_model || EMBEDDING_DEFAULTS.api_model,
    api_key: '',
  }
}

async function loadSettings() {
  settingsLoading.value = true
  settingsLoaded.value = false
  try {
    const data = await getMemorySettings()
    applySettings(data || {})
    settingsLoaded.value = true
  } catch {
    settingsLoaded.value = false
  } finally {
    settingsLoading.value = false
  }
}

function openSettings() {
  settingsVisible.value = true
  loadSettings()
}

async function saveSettings() {
  if (!settingsLoaded.value) return

  const payload = { ...settingsForm }
  for (const key of NUMERIC_SETTING_KEYS) {
    const raw = settingsForm[key]
    if (raw === null || raw === undefined || raw === '') {
      ElMessage.warning('请填写完整的数值参数后再保存')
      return
    }
    const numeric = Number(raw)
    if (!Number.isFinite(numeric)) {
      ElMessage.warning('存在无效的数值参数，请检查后重试')
      return
    }
    payload[key] = numeric
  }

  // embedding 段：API Key 留空时不提交，避免覆盖已保存密钥
  const embedding = { ...settingsForm.embedding }
  embedding.dim = Number(embedding.dim) || 512
  if (!String(embedding.api_key || '').trim()) delete embedding.api_key
  payload.embedding = embedding

  settingsSaving.value = true
  try {
    const data = await updateMemorySettings(payload)
    ElMessage.success(data?.message || '设置已保存，部分参数下一轮对话生效')
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    settingsSaving.value = false
  }
}

watch(query, () => {
  ++listRequestId
  loadedQueryKey.value = ''
  loading.value = false
  listError.value = ''
  page.value = 1
  clearTable()
}, { flush: 'sync' })

onMounted(async () => {
  await loadAccounts()
  await Promise.all([loadStats(), loadList()])
})
</script>

<style scoped>
.memory-overview { border: 1px solid var(--yx-line); border-radius: var(--yx-radius); background: var(--yx-card); }
.overview-heading, .overview-foot { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px 20px; padding: 16px 24px; }
.overview-heading { font-size: 13px; color: var(--yx-text-2); align-items: center; }
.library-picker { display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1; }
.library-picker > label { flex-shrink: 0; }
.library-picker :deep(.el-select) { width: 100%; max-width: 480px; }
.backend-status { display: inline-flex; align-items: center; gap: 7px; color: var(--yx-text-2); font-size: 12px; }
.backend-status i { width: 6px; height: 6px; border-radius: 50%; background: var(--el-color-success); }
.backend-status i.degraded { background: var(--el-color-warning); }
.backend-status i.pending { background: var(--yx-muted); }
.memory-metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); padding: 8px 0 22px; }
.memory-metric { display: flex; flex-direction: column; gap: 12px; padding: 0 24px; }
.memory-metric + .memory-metric { border-left: 1px solid var(--yx-line); }
.metric-label { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--yx-muted); }
.memory-metric strong { font-size: 28px; font-weight: 500; line-height: 1.2; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.memory-metric:first-child strong { color: var(--yx-accent); }
.overview-foot { border-top: 1px solid var(--yx-line); padding-top: 12px; padding-bottom: 12px; line-height: 1.6; }
.memory-guide { color: var(--yx-muted); font-size: 12px; margin-top: -8px; }
.memory-guide summary { width: fit-content; cursor: pointer; padding: 4px 0; }
.memory-guide summary:hover { color: var(--yx-accent); }
.memory-guide-body { display: flex; flex-wrap: wrap; gap: 8px 24px; padding: 8px 0 0; }
.memory-guide p { flex: 1 1 240px; margin: 0; line-height: 1.8; }
.memory-guide strong { color: var(--yx-text-2); font-weight: 500; }
.maintenance-item { display: inline-flex; align-items: center; gap: 8px; }
.memory-filters { display: grid; grid-template-columns: minmax(200px, 2fr) minmax(160px, 1fr) auto; gap: 20px 16px; align-items: end; }
.advanced-filters { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; padding-top: 20px; border-top: 1px solid var(--yx-line); }
.query-field { min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.query-label { color: var(--yx-text-2); font-size: 12px; }
.optional { font-size: 12px; color: var(--yx-muted); margin-left: 4px; }
.query-actions { display: flex; align-items: center; gap: 8px; }
.query-actions :deep(.el-button + .el-button) { margin-left: 0; }
.filter-toggle :deep(.el-icon) { margin-left: 8px; }
.filter-toggle :deep(.is-expanded) { transform: rotate(180deg); }
.filter-count { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px; margin-left: 6px; border-radius: 4px; background: var(--yx-accent-soft); color: var(--yx-accent); font-size: 11px; font-variant-numeric: tabular-nums; }
.memory-results { min-width: 0; }
.results-heading { flex-wrap: wrap; gap: 12px; }
.results-title { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.result-count { padding: 2px 8px; border: 1px solid var(--yx-line); border-radius: 5px; font-size: 12px; color: var(--yx-text-2); font-variant-numeric: tabular-nums; }
.batch-bar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px 16px; padding: 12px 16px; margin-bottom: 16px; border-radius: 8px; background: var(--yx-elevated); }
.batch-summary { color: var(--yx-text-2); font-size: 12px; }
.batch-summary strong { color: var(--yx-accent); }
.batch-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.batch-actions :deep(.el-button + .el-button) { margin-left: 0; }
.memory-table :deep(.el-table__cell) { padding: 17px 0; }
.memory-content { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; line-clamp: 3; overflow: hidden; width: 100%; border: 0; padding: 0; background: transparent; text-align: left; font: inherit; font-size: 14px; color: var(--yx-text); line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; cursor: pointer; }
.memory-content:hover { color: var(--yx-accent); }
.memory-content:focus-visible { outline: 2px solid var(--yx-accent); outline-offset: 3px; border-radius: 3px; }
.memory-content.is-rejected { color: var(--yx-muted); }
.entry-tags, .detail-keywords { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.keyword-tag { color: var(--yx-muted); font-size: 11px; padding: 1px 6px; border: 1px solid var(--yx-line); border-radius: 4px; overflow-wrap: anywhere; max-width: 100%; }
.subject-id { display: block; color: var(--yx-text-2); font-size: 12px; overflow-wrap: anywhere; }
.entry-secondary { display: block; margin-top: 4px; color: var(--yx-muted); font-size: 11px; overflow-wrap: anywhere; }
.tier-marker { display: inline-flex; gap: 6px; align-items: center; font-size: 12px; white-space: nowrap; }
.tier-marker::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: var(--yx-muted); flex-shrink: 0; }
.tier-marker.hot::before { background: var(--el-color-danger); }
.tier-marker.warm::before { background: var(--el-color-warning); }
.entry-time { font-size: 11px; color: var(--yx-muted); }
.table-actions { display: flex; align-items: center; gap: 12px; }
.table-actions :deep(.el-button + .el-button) { margin-left: 0; }
.list-error { display: flex; justify-content: space-between; align-items: center; gap: 16px; min-height: 150px; color: var(--el-color-danger); font-size: 13px; }
.memory-pagination { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; padding-top: 20px; }
.memory-pagination :deep(.el-select) { width: 88px; }
.memory-pagination :deep(.el-pagination) { margin-top: 0; }
.mobile-memories { display: none; }
.detail-tags, .detail-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.detail-content { margin: 24px 0 16px; font-size: 16px; line-height: 1.9; white-space: pre-wrap; overflow-wrap: anywhere; }
.summary-intro { margin: 16px 0 0; line-height: 1.7; }
.detail-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px 24px; margin: 28px 0; padding-top: 24px; border-top: 1px solid var(--yx-line); }
.detail-fields dt { font-size: 12px; color: var(--yx-muted); margin-bottom: 8px; }
.detail-fields dd { margin: 0; font-size: 13px; color: var(--yx-text-2); line-height: 1.7; overflow-wrap: anywhere; }
.detail-id { overflow-wrap: anywhere; }
.detail-actions :deep(.el-button + .el-button) { margin-left: 0; }
.editor-intro { margin: 0 0 24px; line-height: 1.7; }
.editor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.editor-grid :deep(.el-select) { width: 100%; }
@media (max-width: 1100px) {
  .memory-filters { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
  .query-actions { grid-column: 1 / -1; }
  .memory-metric { padding: 0 18px; }
}
@media (max-width: 760px) {
  .memory-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 12px; }
  .keyword-field { grid-column: span 2; }
  .user-field { grid-column: span 2; }
  .query-actions { grid-column: 1 / -1; flex-wrap: wrap; }
  .query-actions :deep(.el-button) { flex: 1; }
  .advanced-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 12px; padding-top: 16px; }
  .library-picker { flex-basis: 100%; flex-direction: column; align-items: stretch; gap: 8px; }
  .library-picker :deep(.el-select) { max-width: none; }
  .memory-metrics { grid-template-columns: repeat(5, minmax(0, 1fr)); padding: 12px 0 20px; }
  .memory-metric { padding: 0 8px; gap: 8px; text-align: center; }
  .memory-metric strong { font-size: 22px; }
  .overview-heading, .overview-foot { padding-left: 16px; padding-right: 16px; }
  .overview-foot { gap: 6px; font-size: 11px; }
  .metric-label { justify-content: center; font-size: 10px; white-space: nowrap; }
  .metric-label :deep(.el-icon) { display: none; }
  .memory-table { display: none; }
  .mobile-memories { display: block; min-height: 100px; }
  .mobile-memory { padding: 18px 0; border-bottom: 1px solid var(--yx-line); }
  .mobile-memory:last-child { border-bottom: 0; }
  .mobile-entry-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; font-size: 12px; color: var(--yx-text-2); overflow-wrap: anywhere; }
  .mobile-entry-heading :deep(.el-checkbox) { margin-right: 0; }
  .mobile-entry-meta { display: flex; flex-wrap: wrap; gap: 8px 14px; font-size: 11px; color: var(--yx-muted); margin-top: 12px; overflow-wrap: anywhere; }
  .mobile-entry-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 14px; }
  .mobile-entry-footer :deep(.el-button) { min-height: 36px; }
  .mobile-memories .memory-content { -webkit-line-clamp: 4; line-clamp: 4; }
  .memory-pagination { justify-content: center; }
  .memory-pagination :deep(.el-pagination) { margin: 0; }
  .editor-grid { grid-template-columns: 1fr; }
}
.settings-body {
  min-height: 220px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.settings-load-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border: 1px solid var(--el-color-danger);
  border-radius: 10px;
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
  font-size: 13px;
}

.settings-section + .settings-section {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--yx-line);
}

.settings-section-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-bottom: 12px;
}

.settings-section-title h4 {
  margin: 0;
  color: var(--yx-text);
  font-size: 14px;
  font-weight: 600;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.settings-grid :deep(.el-form-item) {
  margin-bottom: 16px;
}

.settings-grid :deep(.el-input-number) {
  width: 100%;
}

.switch-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 32px;
}

.drawer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px 16px;
}

.drawer-footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.drawer-footer-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

@media (max-width: 620px) {
  .detail-actions :deep(.el-button) { flex: 1; }
  .mobile-entry-footer > div { display: flex; gap: 8px; }
  .detail-fields { gap: 20px 16px; }
  .query-actions {
    width: 100%;
  }

  .query-actions :deep(.el-button) {
    flex: 1;
  }

  .batch-actions {
    width: 100%;
  }

  .settings-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 420px) {
  .memory-filters { grid-template-columns: 1fr; }
  .keyword-field, .user-field, .query-actions { grid-column: auto; }
  .advanced-filters { grid-template-columns: 1fr; }
  .memory-pagination { gap: 8px 6px; }
  .memory-pagination :deep(.el-pagination) { flex-basis: 100%; justify-content: center; }
  .drawer-footer-actions { width: 100%; }
  .drawer-footer-actions :deep(.el-button) { flex: 1; }
}
</style>
