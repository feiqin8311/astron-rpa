<script setup lang="ts">
import { Auth } from '@rpa/components/auth'
import { theme } from 'ant-design-vue'
import { to } from 'await-to-js'
import { onMounted, onUnmounted, ref } from 'vue'

import { base64ToString } from '@/utils/common'
import BUS from '@/utils/eventBus'
import { storage } from '@/utils/storage'

import BootHeader from '@/components/Boot/Header.vue'
import LaunchCarousel from '@/components/Boot/LaunchCarousel.vue'
import ConfigProvider from '@/components/ConfigProvider/index.vue'
import Loading from '@/components/Loading.vue'
import { utilsManager, windowManager } from '@/platform'

const { token } = theme.useToken()
const progress = ref(0)

function loginWindowStep() {
  windowManager.restoreLoginWindow()
}

function launchProgressCallback(msg: { step: number }) {
  progress.value = msg.step
}

utilsManager.listenEvent('scheduler-event', (eventMsg) => {
  const msgObject = JSON.parse(base64ToString(eventMsg))
  const { type, msg } = msgObject
  console.log('主进程消息: ', msgObject)
  switch (type) {
    case 'sync': {
      // 启动进度
      launchProgressCallback(msg)
      break
    }
    case 'sync_cancel': {
      storage.set('route_port', msg?.route_port)
      sessionStorage.setItem('launch', '1')
      loginAuto()
      break
    }
    default:
      break
  }
})

function loginAuto() {
  // 单人本地使用模式：隐藏并跳过登录注册界面，直接进入主应用
  loginSuccess({ name: '本地用户', loginName: 'admin' })
}

function loginSuccess(userInfo: any) {
  console.log('登录成功: ', userInfo)
  location.replace(`/index.html`)
}

onMounted(() => {
  loginWindowStep()
})

window.onload = async () => {
  if (sessionStorage.getItem('launch') === '1') {
    loginAuto()
    return
  }
  const [err] = await to(utilsManager.invoke('main_window_onload'))
  if (err) {
    console.error('main_window_onload 调用失败: ', err)
    loginAuto()
  }
}

onUnmounted(() => {
  BUS.$off('launch-progress', launchProgressCallback)
})
</script>

<template>
  <ConfigProvider>
    <Auth.PageLayout>
      <template #header>
        <BootHeader />
      </template>
      <template #container>
        <div
          class="flex items-center justify-center"
        >
          <LaunchCarousel>
            <template #footer>
              <div class="mt-6 w-[280px]">
                <a-progress
                  :percent="progress"
                  :show-info="false"
                  :stroke-color="token.colorPrimary"
                  trail-color="rgba(255, 255, 255, 0.12)"
                />
              </div>
            </template>
          </LaunchCarousel>
        </div>
      </template>
      <!-- 单人本地模式：隐藏登录与注册表单 -->
    </Auth.PageLayout>
    <Loading />
  </ConfigProvider>
</template>
