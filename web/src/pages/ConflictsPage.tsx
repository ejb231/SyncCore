import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Check, Trash2 } from 'lucide-react'

export default function ConflictsPage() {
  const qc = useQueryClient()
  const { data = [], isLoading } = useQuery({ queryKey: ['conflicts'], queryFn: api.getConflicts, refetchInterval: 10000 })

  const resolve = useMutation({
    mutationFn: ({ id, del }: { id: number; del: boolean }) => api.resolveConflict(id, del),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conflicts'] }),
  })

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Conflicts</h2>
      {isLoading ? <p className="text-gray-500">Loading…</p> : (
        <div className="bg-white rounded-xl shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-4 py-3">Path</th>
                <th className="text-left px-4 py-3">Conflict File</th>
                <th className="text-left px-4 py-3">Origin</th>
                <th className="text-left px-4 py-3">Detected</th>
                <th className="text-left px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.map(c => (
                <tr key={c.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono">{c.path}</td>
                  <td className="px-4 py-2 font-mono text-xs">{c.conflict_file}</td>
                  <td className="px-4 py-2">{c.origin}</td>
                  <td className="px-4 py-2">{new Date(c.detected_at * 1000).toLocaleString()}</td>
                  <td className="px-4 py-2 flex gap-2">
                    <button
                      onClick={() => resolve.mutate({ id: c.id, del: false })}
                      className="flex items-center gap-1 text-green-600 hover:bg-green-50 px-2 py-1 rounded text-xs"
                      title="Keep both"
                    >
                      <Check size={14} /> Keep Both
                    </button>
                    <button
                      onClick={() => resolve.mutate({ id: c.id, del: true })}
                      className="flex items-center gap-1 text-red-600 hover:bg-red-50 px-2 py-1 rounded text-xs"
                      title="Resolve & delete conflict file"
                    >
                      <Trash2 size={14} /> Delete Copy
                    </button>
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No unresolved conflicts</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
