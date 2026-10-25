<template>
  <el-container class="yx-layout">
    <a class="yx-skip-link" href="#main-content">跳到主要内容</a>
    <el-aside v-if="!isMobile" :width="app.collapsed ? '72px' : '232px'" class="yx-aside">
      <SideNavigation :collapsed="app.collapsed" />
    </el-aside>

    <el-drawer v-model="mobileOpen" title="导航" direction="ltr" size="264px" class="yx-nav-drawer" :with-header="false">
      <SideNavigation @navigate="mobileOpen = false" />
    </el-drawer>

    <el-container class="yx-workspace">
      <el-header class="yx-header">
        <el-button text circle :aria-label="isMobile ? '打开导航' : app.collapsed ? '展开侧栏' : '收起侧栏'" :aria-expanded="isMobile ? mobileOpen : !app.collapsed" @click="isMobile ? mobileOpen = true : app.toggleSidebar()">
          <el-icon :size="18">
            <Expand v-if="isMobile || app.collapsed" />
            <Fold v-else />
          </el-icon>
        </el-button>
        <nav class="yx-header-path" aria-label="当前位置">
          <span class="yx-header-crumb">{{ route.meta.group || '工作空间' }} <span aria-hidden="true">/</span></span>
          <span class="yx-header-title" aria-current="page">{{ route.meta.title || '控制台' }}</span>
        </nav>
        <div class="yx-header-spacer"></div>

        <span class="yx-health" :class="{ 'is-error': health.ok === false }" role="status">
          <span class="yx-status-dot" :class="{ 'is-pending': health.ok === null }"></span>{{ health.label }}
        </span>

        <el-dropdown trigger="click" @command="handleCommand">
          <button type="button" class="yx-user" aria-label="用户菜单">
            <span class="yx-avatar">{{ initial }}</span>
            <span class="yx-user-name">{{ auth.displayName }}</span>
            <el-icon :size="12"><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password">
                <el-icon><Lock /></el-icon>修改密码
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main id="main-content" class="yx-main" tabindex="-1">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>

    <el-dialog v-model="passwordVisible" title="修改密码" width="420px">
      <el-form label-position="top" :model="passwordForm">
        <el-form-item label="原密码">
          <el-input v-model="passwordForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input
            v-model="passwordForm.new_password"
            type="password"
            show-password
            placeholder="至少 6 位"
          />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="passwordForm.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitPassword">
          保存
        </el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Expand, Fold, Lock, SwitchButton } from '@element-plus/icons-vue'

import SideNavigation from '@/components/SideNavigation.vue'
import { changePassword } from '@/api/auth'
import { getHealth } from '@/api/system'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const auth = useAuthStore()

const initial = computed(() => (auth.displayName || '月').slice(0, 1))
const health = reactive({ ok: null, label: '正在连接' })
const mobileQuery = window.matchMedia('(max-width: 760px)')
const isMobile = ref(mobileQuery.matches)
const mobileOpen = ref(false)
function updateViewport(event) {
  isMobile.value = event.matches
  mobileOpen.value = false
}
let healthTimer = null

async function loadHealth() {
  try {
    const data = await getHealth()
    health.ok = data.status === 'ok'
    health.label = health.ok ? '服务正常' : '服务降级'
  } catch {
    health.ok = false
    health.label = '服务不可用'
  }
}

const passwordVisible = ref(false)
const submitting = ref(false)
const passwordForm = reactive({ old_password: '', new_password: '', confirm: '' })

function handleCommand(command) {
  if (command === 'password') {
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    passwordForm.confirm = ''
    passwordVisible.value = true
  } else if (command === 'logout') {
    auth.logout()
    router.push('/login')
    ElMessage.success('已退出登录')
  }
}

async function submitPassword() {
  if (!passwordForm.old_password || !passwordForm.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  if (passwordForm.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  submitting.value = true
  try {
    await changePassword({
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
    })
    ElMessage.success('密码已修改，请重新登录')
    passwordVisible.value = false
    auth.logout()
    router.push('/login')
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  mobileQuery.addEventListener('change', updateViewport)
  loadHealth()
  healthTimer = window.setInterval(loadHealth, 60000)
})

onBeforeUnmount(() => {
  mobileQuery.removeEventListener('change', updateViewport)
  if (healthTimer) window.clearInterval(healthTimer)
})
</script>

<style scoped>
.yx-user-name {
  font-size: 13px;
  color: var(--yx-text-2);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

</style>
