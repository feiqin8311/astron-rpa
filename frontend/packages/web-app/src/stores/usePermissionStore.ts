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
  const isLocalAuthMode = import.meta.env.VITE_AUTH_MODE === 'local'
  const permissionAction = ref<PermItem[]>(isLocalAuthMode ? DEFAULT_PERMISSIONS : [])
  const fetched = ref(false)

  const initPermission = async () => {
    if (fetched.value)
      return
    try {
      const data = await permission()
      if (data && data.length > 0) {
        setPermission(data)
      }
      else if (isLocalAuthMode) {
        setPermission(DEFAULT_PERMISSIONS)
      }
      fetched.value = true
    }
    catch (e) {
      if (isLocalAuthMode) {
        console.warn('[Permission] fetch failed, fallback to all permissions in local mode', e)
        setPermission(DEFAULT_PERMISSIONS)
      }
      else {
        console.error('[Permission] fetch failed', e)
      }
      fetched.value = true
    }
  }

  const setPermission = (value: PermItem[]) => {
    permissionAction.value = value
  }

  const can = (resource: string, action = 'all'): boolean => {
    if (isLocalAuthMode) {
      return true
    }
    return permissionAction.value.some(
      p => p.resource === resource && p.actions?.includes(action),
    )
  }

  const reset = () => {
    permissionAction.value = isLocalAuthMode ? DEFAULT_PERMISSIONS : []
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
