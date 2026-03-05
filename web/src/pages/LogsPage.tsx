import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { LogEntry } from '../api/types'
import { useWebSocket } from '../hooks/useWebSocket'

const LEVELS = ['', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
const levelColor: Record<string, string> = {
  DEBUG: 'text-gray-500',
  INFO: 'text-blue-600',
  WARNING: 'text-amber-600',
  ERROR: 'text-red-600',
  CRITICAL: 'text-red-800 font-bold',
}

export default function LogsPage() {
  const [level, setLevel] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const containerRef = useRef<HTMLDivElement>(null)
  const { logs: wsLogs } = useWebSocket()

  const { data: initialLogs = [] } = useQuery({
    queryKey: ['logs', level],
    queryFn: () => api.getLogs(level || undefined),
    refetchInterval: false,
  })

  const [allLogs, setAllLogs] = useState<LogEntry[]>([])

  useEffect(() => {
    setAllLogs(initialLogs)
  }, [initialLogs])

  useEffect(() => {
    if (wsLogs.length > 0) {
      const last = wsLogs[wsLogs.length - 1]
      if (!level || last.level === level) {
        setAllLogs(prev => [...prev, last].slice(-1000))
      }
    }
  }, [wsLogs, level])

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [allLogs, autoScroll])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Logs</h2>
        <div className="flex items-center gap-4">
          <select
            value={level}
            onChange={e => setLevel(e.target.value)}
            className="border rounded-lg px-3 py-1.5 text-sm"
          >
            {LEVELS.map(l => <option key={l} value={l}>{l || 'All Levels'}</option>)}
          </select>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} />
            Auto-scroll
          </label>
        </div>
      </div>
      <div ref={containerRef} className="bg-gray-900 text-gray-200 rounded-xl p-4 font-mono text-xs flex-1 overflow-auto max-h-[70vh]">
        {allLogs.map((entry, i) => (
          <div key={i} className="leading-5">
            <span className="text-gray-500">{new Date(entry.timestamp * 1000).toLocaleTimeString()}</span>
            {' '}
            <span className={levelColor[entry.level] || 'text-gray-400'}>[{entry.level}]</span>
            {' '}
            <span className="text-gray-400">{entry.name}</span>
            {' '}
            <span>{entry.message}</span>
          </div>
        ))}
        {allLogs.length === 0 && <div className="text-gray-500 text-center py-8">No log entries</div>}
      </div>
    </div>
  )
}
