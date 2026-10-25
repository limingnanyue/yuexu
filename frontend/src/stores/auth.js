import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('yuexu_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('yuexu_user') || 'null'))

  const isLoggedIn = computed(() => Boolean(token.value))
  const isOwner = computed(() => user.value?.role === 'owner')
  const displayName = computed(
    () => user.value?.nickname || user.value?.username || '未登录',
  )

  function persist() {
    if (token.value) {
      localStorage.setItem('yuexu_token', token.value)
    } else {
      localStorage.removeItem('yuexu_token')
    }
    if (user.value) {
      localStorage.setItem('yuexu_user', JSON.stringify(user.value))
    } else {
      localStorage.removeItem('yuexu_user')
    }
  }

  async function login(credentials) {
    const data = await authApi.login(credentials)
    token.value = data.token
    user.value = data.user
    persist()
    return data
  }

  async function fetchMe() {
    const data = await authApi.getMe()
    user.value = data
    persist()
    return data
  }

  function logout() {
    token.value = ''
    user.value = null
    persist()
  }

  return { token, user, isLoggedIn, isOwner, displayName, login, fetchMe, logout }
})
