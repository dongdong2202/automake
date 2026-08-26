<template>
  <el-tooltip :content="content" placement="top" :effect="effect">
    <el-icon class="guide-icon"><QuestionFilled /></el-icon>
  </el-tooltip>
</template>

<script setup lang="ts">
import { QuestionFilled } from '@element-plus/icons-vue'

defineProps({
  content: {
    type: String,
    required: true,
  },
  effect: {
    type: String,
    default: 'dark',
  },
})
</script>

<style scoped>
.guide-icon {
  color: #909399;
  cursor: pointer;
  margin-left: 4px;
  font-size: 14px;
  vertical-align: middle;
}
.guide-icon:hover {
  color: #409EFF;
}
</style>
