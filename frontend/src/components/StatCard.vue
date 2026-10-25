<template>
  <div class="yx-stat">
    <div class="yx-stat-label">{{ label }}</div>
    <div class="yx-stat-value">
      {{ value }}
      <span v-if="suffix" class="yx-stat-suffix">{{ suffix }}</span>
    </div>
    <el-icon v-if="icon" class="yx-stat-icon" aria-hidden="true">
      <component :is="icon" />
    </el-icon>
    <div v-if="note" class="yx-stat-note">{{ note }}</div>
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: 0 },
  suffix: { type: String, default: '' },
  icon: { type: String, default: '' },
  note: { type: String, default: '' },
})
</script>
