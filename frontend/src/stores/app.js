import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', () => {
  const collapsed = ref(localStorage.getItem('yuexu_sidebar') === 'collapsed')

  function toggleSidebar() {
    collapsed.value = !collapsed.value
    localStorage.setItem('yuexu_sidebar', collapsed.value ? 'collapsed' : 'expanded')
  }

  return { collapsed, toggleSidebar }
})
