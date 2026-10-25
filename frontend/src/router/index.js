import { createRouter, createWebHistory } from 'vue-router'

import pinia from '@/stores'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login/index.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/Dashboard/index.vue'),
        meta: { title: '总览', group: '概览' },
      },
      {
        path: 'accounts',
        name: 'accounts',
        component: () => import('@/views/AccountManage/index.vue'),
        meta: { title: '账号与机器人', group: '机器人' },
      },
      {
        path: 'characters',
        name: 'characters',
        component: () => import('@/views/Character/index.vue'),
        meta: { title: '人设管理', group: '对话配置' },
      },
      {
        path: 'emotions',
        name: 'emotions',
        component: () => import('@/views/EmotionState/index.vue'),
        meta: { title: '情感状态', group: '对话配置' },
      },
      {
        path: 'memory',
        name: 'memory',
        component: () => import('@/views/MemoryManage/index.vue'),
        meta: { title: '记忆管理', group: '对话配置' },
      },
      {
        path: 'contexts',
        name: 'contexts',
        component: () => import('@/views/ContextManage/index.vue'),
        meta: { title: '上下文会话', group: '对话配置' },
      },
      {
        path: 'models',
        name: 'models',
        component: () => import('@/views/LlmConfig/index.vue'),
        meta: { title: '模型配置', group: '对话配置' },
      },
      {
        path: 'groups',
        name: 'groups',
        component: () => import('@/views/GroupRule/index.vue'),
        meta: { title: '群组规则', group: '对话配置' },
      },
      {
        path: 'push',
        name: 'push',
        component: () => import('@/views/AutoPushTask/index.vue'),
        meta: { title: '私聊惦记', group: '对话配置' },
      },
      {
        path: 'vitality',
        name: 'vitality',
        component: () => import('@/views/VitalityAgent/index.vue'),
        meta: { title: '活力 Agent', group: '对话配置' },
      },
      {
        path: 'emojis',
        name: 'emojis',
        component: () => import('@/views/EmojiLib/index.vue'),
        meta: { title: '表情库', group: '内容与能力' },
      },
      {
        path: 'tts',
        name: 'tts',
        component: () => import('@/views/TtsSetting/index.vue'),
        meta: { title: 'TTS 语音', group: '内容与能力' },
      },
      {
        path: 'images',
        name: 'images',
        component: () => import('@/views/ImageSetting/index.vue'),
        meta: { title: 'AI 生图', group: '内容与能力' },
      },
      {
        path: 'search',
        name: 'search',
        component: () => import('@/views/SearchSetting/index.vue'),
        meta: { title: '联网搜索', group: '内容与能力' },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@/views/LogPage/index.vue'),
        meta: { title: '日志', group: '系统' },
      },
      {
        path: 'system',
        name: 'system',
        component: () => import('@/views/SystemSetting/index.vue'),
        meta: { title: '系统设置', group: '系统' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  document.title = `${to.meta.title || '控制台'} · 月叙`
  if (to.meta.public) return true

  const auth = useAuthStore(pinia)
  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.logout()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  return true
})

export default router
