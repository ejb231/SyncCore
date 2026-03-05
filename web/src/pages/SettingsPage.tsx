import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Save, AlertCircle } from 'lucide-react'

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['config'], queryFn: api.getConfig })
  const [form, setForm] = useState<Record<string, string>>({})
  const [restartBanner, setRestartBanner] = useState(false)
  const [saved, setSaved] = useState(false)

  const save = useMutation({
    mutationFn: (updates: Record<string, unknown>) => api.putConfig(updates),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['config'] })
      setForm({})
      if (res.restart_required) setRestartBanner(true)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  if (isLoading || !data) return <p className="text-gray-500 p-8">Loading…</p>

  const fields = Object.entries(data).filter(([k]) => k !== 'api_key' && k !== 'admin_token')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (Object.keys(form).length > 0) save.mutate(form)
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Settings</h2>
      {restartBanner && (
        <div className="bg-amber-100 border border-amber-300 text-amber-800 px-4 py-3 rounded-lg mb-4 flex items-center gap-2">
          <AlertCircle size={18} /> Restart required for port/SSL changes to take effect.
        </div>
      )}
      {saved && <div className="bg-green-100 border border-green-300 text-green-800 px-4 py-2 rounded-lg mb-4">Settings saved.</div>}
      <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow p-6 max-w-2xl space-y-4">
        {fields.map(([key, value]) => (
          <div key={key}>
            <label className="block text-sm font-medium text-gray-600 mb-1">{key}</label>
            <input
              className="w-full border rounded-lg px-3 py-2 text-sm"
              defaultValue={String(value)}
              onChange={e => setForm(prev => ({ ...prev, [key]: e.target.value }))}
            />
          </div>
        ))}
        <button
          type="submit"
          disabled={Object.keys(form).length === 0}
          className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          <Save size={16} /> Save Changes
        </button>
      </form>
    </div>
  )
}
