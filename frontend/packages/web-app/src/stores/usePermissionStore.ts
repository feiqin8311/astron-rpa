import { defineStore } from 'pinia'
import { ref } from 'vue'

import { permission } from '@/api/permission' // 换成你的请求实例
import { ACTUATOR, APPLICATIONMARKET, DESIGNER } from '@/constants/menu'

export interface PermItem {
  resource: string
  actions: string[]
}

const DEFAULT_PERMISSIONS: PermItem[] = [
  { resource: DESIGNER, actions: ['all'] },
  { resource: ACTUATOR, actions: ['all'] },
  { resource: 'console', actions: ['all'] },
  { resource: APPLICATIONMARKET, actions: ['all'] },
]

export const usePermissionStore = defineStore('permission', () => {
  const permissionAction = ref<PermItem[]>(DEFAULT_PERMISSIONS)
  const fetched = ref(false)

  const initPermission = async () => {
    if (fetched.value)
      return
    try {
      const data = await permission()
      if (data && data.length > 0) {
        setPermission(data)
      }
      else {
        setPermission(DEFAULT_PERMISSIONS)
      }
      fetched.value = true
    }
    catch (e) {
      console.warn('[Permission] fetch failed, fallback to all permissions', e)
      setPermission(DEFAULT_PERMISSIONS)
      fetched.value = true
    }
  }

  const setPermission = (value: PermItem[]) => {
    permissionAction.value = value
  }

  const can = (_resource: string, _action = 'all'): boolean => {
    // 单人模式：默认拥有全部权限
    return true
  }

  const reset = () => {
    permissionAction.value = DEFAULT_PERMISSIONS
    fetched.value = false
  }

  return {
    initPermission,
    setPermission,
    permissionAction,
    can,
    reset,
    fetched,
  }
})
