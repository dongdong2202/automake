<template>
  <div class="page-header">
    <div class="header-left">
      <h2 class="title">{{ title }}</h2>
      <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
    </div>
    <div class="header-right">
      <slot name="actions"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps({
  title: {
    type: String,
    required: true,
  },
  subtitle: {
    type: String,
    default: '',
  },
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
  background: #ffffff;
  padding: 16px 20px;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.06);
}
.title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  line-height: 1.2;
}
.subtitle {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
