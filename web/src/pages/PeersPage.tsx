import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Plus, Trash2, Wifi, WifiOff } from 'lucide-react'

export default function PeersPage() {
  const qc = useQueryClient()
  const { data = [], isLoading } = useQuery({ queryKey: ['peers'], queryFn: api.getPeers, refetchInterval: 10000 })
  const [newUrl, setNewUrl] = useState('')

  const add = useMutation({
    mutationFn: (url: string) => api.addPeer(url),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['peers'] }); setNewUrl('') },
  })
  const remove = useMutation({
    mutationFn: (url: string) => api.removePeer(url),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['peers'] }),
  })

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Peers</h2>
      <div className="flex gap-2 mb-4 max-w-lg">
        <input
          className="flex-1 border rounded-lg px-4 py-2 text-sm"
          placeholder="https://peer:8443"
          value={newUrl}
          onChange={e => setNewUrl(e.target.value)}
        />
        <button
          onClick={() => newUrl && add.mutate(newUrl)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm flex items-center gap-1 hover:bg-blue-700"
        >
          <Plus size={16} /> Add
        </button>
      </div>
      {isLoading ? <p className="text-gray-500">Loading…</p> : (
        <div className="bg-white rounded-xl shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-4 py-3">URL</th>
                <th className="text-left px-4 py-3">Node ID</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-left px-4 py-3">Last Seen</th>
                <th className="text-left px-4 py-3">Failures</th>
                <th className="text-left px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.map(p => (
                <tr key={p.url} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-xs">{p.url}</td>
                  <td className="px-4 py-2">{p.node_id}</td>
                  <td className="px-4 py-2">
                    {p.alive
                      ? <span className="inline-flex items-center gap-1 text-green-600"><Wifi size={14} /> Online</span>
                      : <span className="inline-flex items-center gap-1 text-red-500"><WifiOff size={14} /> Offline</span>
                    }
                  </td>
                  <td className="px-4 py-2">{new Date(p.last_seen * 1000).toLocaleString()}</td>
                  <td className="px-4 py-2">{p.failures}</td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => remove.mutate(p.url)}
                      className="text-red-600 hover:bg-red-50 p-1 rounded"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No peers connected</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
