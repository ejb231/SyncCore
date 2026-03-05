import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Search, AlertTriangle } from 'lucide-react'

export default function FilesPage() {
  const [search, setSearch] = useState('')
  const { data = [], isLoading } = useQuery({
    queryKey: ['files', search],
    queryFn: () => api.getFiles(search || undefined),
    refetchInterval: 10000,
  })

  function fmtSize(bytes: number) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1048576).toFixed(1)} MB`
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Files</h2>
      <div className="relative mb-4 max-w-md">
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          className="w-full border rounded-lg pl-10 pr-4 py-2 text-sm"
          placeholder="Search files…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>
      {isLoading ? <p className="text-gray-500">Loading…</p> : (
        <div className="bg-white rounded-xl shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-4 py-3">Path</th>
                <th className="text-left px-4 py-3">Size</th>
                <th className="text-left px-4 py-3">Hash</th>
                <th className="text-left px-4 py-3">Origin</th>
                <th className="text-left px-4 py-3">Ver</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.map(f => (
                <tr key={f.path} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono flex items-center gap-2">
                    {f.path.toLowerCase().includes('conflict') && <AlertTriangle size={14} className="text-amber-500" />}
                    {f.path}
                  </td>
                  <td className="px-4 py-2">{fmtSize(f.size)}</td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-500">{f.hash.slice(0, 12)}…</td>
                  <td className="px-4 py-2">{f.origin}</td>
                  <td className="px-4 py-2">{f.version}</td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No files found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
