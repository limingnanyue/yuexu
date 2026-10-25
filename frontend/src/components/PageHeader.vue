<template>
  <div class="yx-page-head">
    <div class="yx-page-heading">
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <div class="yx-page-actions">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<style scoped>
.yx-page-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  justify-content: space-between;
  gap: 20px 32px;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--yx-line);
}

.yx-page-heading { min-width: 0; }

.yx-page-heading h1 {
  margin: 0;
  font-size: 26px;
  font-family: var(--yx-heading-font);
  font-weight: 500;
  line-height: 1.35;
  letter-spacing: -0.01em;
  text-wrap: balance;
}

.yx-page-heading p {
  margin: 8px 0 0;
  color: var(--yx-muted);
  max-width: 65ch;
  font-size: 13px;
  line-height: 1.7;
  text-wrap: pretty;
}

.yx-page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.yx-page-actions:empty { display: none; }

@media (max-width: 1100px) {
  .yx-page-head { display: flex; flex-wrap: wrap; }
  .yx-page-actions { justify-content: flex-start; }
}

@media (max-width: 760px) {
  .yx-page-head { align-items: stretch; gap: 16px; padding-bottom: 20px; }
  .yx-page-heading { width: 100%; }
  .yx-page-heading h1 { font-size: 25px; }
  .yx-page-actions { gap: 8px; }
  .yx-page-actions:empty { display: none; }
}
</style>
