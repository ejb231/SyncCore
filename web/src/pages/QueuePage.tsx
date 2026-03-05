import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { RefreshCw, Trash2, Pause, Play } from 'lucide-react'
import { useState } from 'react'

export default function QueuePage() {
  const qc = useQueryClient()
  const { data = [], isLoading } = useQuery({ queryKey: ['queue'], queryFn: api.getQueue, refetchInterval: 5000 })
  const [paused, setPaused] = useState(false)

  const retry = useMutation({
    mutationFn: (id: number) => api.retryTask(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['queue'] }),
  })
  const clear = useMutation({
    mutationFn: () => api.clearQueue(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['queue'] }),
  })
  const pause = useMutation({
    mutationFn: () => api.pauseQueue(),
    onSuccess: () => setPaused(true),
  })
  const resume = useMutation({
    mutationFn: () => api.resumeQueue(),
    onSuccess: () => setPaused(false),
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Queue</h2>
        <div className="flex gap-2">
          <button
            onClick={() => (paused ? resume : pause).mutate()}
            className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm ${paused ? 'bg-green-600 text-white hover:bg-green-700' : 'bg-yellow-500 text-white hover:bg-yellow-600'}`}
          >
            {paused ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Pause</>}
          </button>
          <button
            onClick={() => clear.mutate()}
            className="flex items-center gap-1 bg-red-600 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-red-700"
          >
            <Trash2 size={14} /> Clear All
          </button>
        </div>
      </div>
      {isLoading ? <p className="text-gray-500">Loading…</p> : (
        <div className="bg-white rounded-xl shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-4 py-3">Action</th>
                <th className="text-left px-4 py-3">Path</th>
                <th className="text-left px-4 py-3">Attempts</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-left px-4 py-3">Next Retry</th>
                <th className="text-left px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.map(t => (
                <tr key={t.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2">{t.action}</td>
                  <td className="px-4 py-2 font-mono text-xs">{t.path}</td>
                  <td className="px-4 py-2">{t.attempts}/{t.max_retries}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${
                      t.status === 'pending' ? 'bg-blue-100 text-blue-700' :
                      t.status === 'failed' ? 'bg-red-100 text-red-700' :
                      'bg-gray-100 text-gray-600'
                    }`}>{t.status}</span>
                  </td>
                  <td className="px-4 py-2">{t.next_retry ? new Date(t.next_retry * 1000).toLocaleTimeString() : '—'}</td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => retry.mutate(t.id)}
                      className="text-blue-600 hover:bg-blue-50 p-1 rounded"
                      title="Retry"
                    >
                      <RefreshCw size={16} />
                    </button>
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">Queue is empty</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
