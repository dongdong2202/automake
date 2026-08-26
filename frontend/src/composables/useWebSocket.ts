import { ref, onMounted, onUnmounted } from 'vue'

export function useWebSocket(url: string, onMessage?: (data: any) => void) {
  const isConnected = ref(false)
  const error = ref<any>(null)
  let ws: WebSocket | null = null
  let reconnectTimer: any = null
  let isDestroyed = false

  function connect() {
    if (isDestroyed) return
    try {
      const fullUrl = url.startsWith('ws')
        ? url
        : `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${url}`

      ws = new WebSocket(fullUrl)

      ws.onopen = () => {
        isConnected.value = true
        error.value = null
        if (reconnectTimer) {
          clearTimeout(reconnectTimer)
          reconnectTimer = null
        }
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          onMessage?.(data)
        } catch (e) {
          onMessage?.(event.data)
        }
      }

      ws.onerror = (e) => {
        error.value = e
      }

      ws.onclose = () => {
        isConnected.value = false
        if (!isDestroyed) {
          reconnectTimer = setTimeout(connect, 3000)
        }
      }
    } catch (err) {
      error.value = err
      if (!isDestroyed) {
        reconnectTimer = setTimeout(connect, 3000)
      }
    }
  }

  function send(data: any) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }

  onMounted(() => {
    isDestroyed = false
    connect()
  })

  onUnmounted(() => {
    isDestroyed = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
    }
    if (ws) {
      ws.close()
      ws = null
    }
  })

  return {
    isConnected,
    error,
    send,
  }
}
