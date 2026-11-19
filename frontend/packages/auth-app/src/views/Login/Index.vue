<script setup lang="ts">
import { onMounted } from 'vue'

function loginSuccess() {
  location.replace(`/admin`)
}

onMounted(() => {
  // 单人模式：直接跳过登录页面进入管理控制台
  loginSuccess()
})
</script>

<template>
  <div class="flex items-center justify-center h-screen bg-[#f5f7fa] text-gray-600">
    <span>正在进入系统...</span>
  </div>
</template>
