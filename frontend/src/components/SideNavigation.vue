<template>
  <nav class="yx-sidebar" aria-label="主导航">
    <router-link to="/dashboard" class="yx-brand" aria-label="月叙 · 返回总览" @click="$emit('navigate')">
      <img :src="logo" width="32" height="32" alt="" />
      <div v-if="!collapsed" class="yx-brand-text">
        <span class="yx-brand-title">月叙 <span class="yx-brand-console">工作台</span></span>
        <span class="yx-brand-sub">AI 对话控制台</span>
      </div>
    </router-link>
    <el-menu
      :default-active="route.path"
      :collapse="collapsed"
      :collapse-transition="false"
      router
      class="yx-menu"
      @select="$emit('navigate')"
    >
      <el-menu-item-group v-for="group in menuGroups" :key="group.title" :title="group.title">
        <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path" :aria-label="item.title">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu-item-group>
    </el-menu>
    <div v-if="!collapsed" class="yx-sidebar-note"><img :src="logo" width="18" height="18" alt="" /><span>月下叙话，记忆留存。</span></div>
  </nav>
</template>

<script setup>
import { useRoute } from 'vue-router'
import logo from '@/assets/yuexu.svg'

defineProps({ collapsed: { type: Boolean, default: false } })
defineEmits(['navigate'])
const route = useRoute()
const menuGroups = [
  { title: '工作空间', items: [
    { path: '/dashboard', title: '总览', icon: 'Odometer' },
    { path: '/accounts', title: '账号与机器人', icon: 'Iphone' },
  ] },
  { title: '对话配置', items: [
    { path: '/characters', title: '人设管理', icon: 'User' },
    { path: '/emotions', title: '情感状态', icon: 'Sunny' },
    { path: '/memory', title: '记忆管理', icon: 'Collection' },
    { path: '/contexts', title: '上下文会话', icon: 'ChatLineSquare' },
    { path: '/models', title: '模型配置', icon: 'Cpu' },
    { path: '/groups', title: '群组规则', icon: 'ChatDotRound' },
    { path: '/push', title: '私聊惦记', icon: 'AlarmClock' },
    { path: '/vitality', title: '活力 Agent', icon: 'MagicStick' },
  ] },
  { title: '内容与能力', items: [
    { path: '/emojis', title: '表情库', icon: 'Picture' },
    { path: '/tts', title: 'TTS 语音', icon: 'Microphone' },
    { path: '/images', title: 'AI 生图', icon: 'Picture' },
    { path: '/search', title: '联网搜索', icon: 'Search' },
  ] },
  { title: '系统', items: [
    { path: '/logs', title: '日志', icon: 'Document' },
    { path: '/system', title: '系统设置', icon: 'Setting' },
  ] },
]
</script>
