import { useEffect, useRef, useCallback, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getAdminToken } from '../api/client'
import type { WSEvent, LogEntry } from '../api/types'

export function useWebSocket() {
  const queryClient = useQueryClient()
  const wsRef = useRef<WebSocket | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [toast, setToast] = useState<string | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const connect = useCallback(() => {
    const token = getAdminToken()
    if (!token) return
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${location.host}/api/v1/ws`)

    ws.onopen = () => {
      // Authenticate via first message instead of query string to avoid
      // leaking the admin token in server access logs.
      ws.send(JSON.stringify({ type: 'auth', token }))
    }

    ws.onmessage = (ev) => {
      try {
        const msg: WSEvent = JSON.parse(ev.data)
        switch (msg.event) {
          case 'file_uploaded':
          case 'file_deleted':
            queryClient.invalidateQueries({ queryKey: ['files'] })
            queryClient.invalidateQueries({ queryKey: ['status'] })
            break
          case 'conflict':
            queryClient.invalidateQueries({ queryKey: ['conflicts'] })
            queryClient.invalidateQueries({ queryKey: ['files'] })
            setToast(`Conflict detected: ${(msg.data as Record<string, string>).path}`)
            setTimeout(() => setToast(null), 5000)
            break
          case 'peer_registered':
            queryClient.invalidateQueries({ queryKey: ['peers'] })
            break
          case 'log':
            setLogs(prev => [...prev.slice(-999), msg.data as unknown as LogEntry])
            break
        }
      } catch { /* ignore parse errors */ }
    }

    ws.onclose = () => {
      reconnectTimer.current = setTimeout(connect, 3000)
    }

    wsRef.current = ws
  }, [queryClient])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { logs, toast }
}
