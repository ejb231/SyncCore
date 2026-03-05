import { useState } from 'react'
import { api, setAdminToken } from '../api/client'
import { Rocket, FolderSync, Key, Globe, User } from 'lucide-react'

export default function SetupPage({ onComplete }: { onComplete: () => void }) {
  const [form, setForm] = useState({ sync_folder: '', api_key: '', node_id: '', peers: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await api.setup(form)
      setAdminToken(res.admin_token)
      onComplete()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl p-8 max-w-lg w-full">
        <div className="flex items-center gap-3 mb-2">
          <div className="bg-blue-600 p-2.5 rounded-xl"><Rocket size={28} className="text-white" /></div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Welcome to SyncCore</h1>
            <p className="text-sm text-gray-500">File synchronisation made simple</p>
          </div>
        </div>

        <p className="text-sm text-gray-600 mt-3 mb-6 leading-relaxed">
          Let's get you set up. All fields below are <strong>optional</strong> — sensible
          defaults have already been configured. Just click <em>Start Syncing</em> to begin,
          or customise the settings below.
        </p>

        {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2.5 rounded-lg mb-4 text-sm">{error}</div>}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1">
              <FolderSync size={15} className="text-blue-500" /> Sync Folder
            </label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              placeholder="Leave empty to use the default folder"
              value={form.sync_folder}
              onChange={e => setForm(f => ({ ...f, sync_folder: e.target.value }))}
            />
            <p className="text-xs text-gray-400 mt-1">The folder on this machine that will stay in sync.</p>
          </div>

          <div>
            <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1">
              <Key size={15} className="text-blue-500" /> API Key
            </label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              placeholder="Leave empty for an auto-generated secure key"
              value={form.api_key}
              onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))}
            />
            <p className="text-xs text-gray-400 mt-1">Shared secret used to authenticate sync connections between nodes.</p>
          </div>

          <div>
            <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1">
              <User size={15} className="text-blue-500" /> Node Name
            </label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              placeholder="Leave empty for an auto-generated name"
              value={form.node_id}
              onChange={e => setForm(f => ({ ...f, node_id: e.target.value }))}
            />
            <p className="text-xs text-gray-400 mt-1">A friendly name for this machine so you can tell nodes apart.</p>
          </div>

          <div>
            <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1">
              <Globe size={15} className="text-blue-500" /> Peers
            </label>
            <input
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              placeholder="e.g. https://192.168.1.10:8443"
              value={form.peers}
              onChange={e => setForm(f => ({ ...f, peers: e.target.value }))}
            />
            <p className="text-xs text-gray-400 mt-1">Comma-separated addresses of other SyncCore nodes. You can add these later.</p>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 disabled:opacity-50 transition-colors text-base"
          >
            {loading ? 'Setting up…' : 'Start Syncing'}
          </button>
        </form>

        <p className="text-xs text-center text-gray-400 mt-5">
          TLS certificates are generated automatically. No extra tools needed.
        </p>
      </div>
    </div>
  )
}
