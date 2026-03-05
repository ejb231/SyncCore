import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Save, AlertCircle, Eye, EyeOff, Copy, Check, Settings, Globe, Shield, Wrench } from 'lucide-react'

interface FieldDef {
  key: string
  label: string
  type: 'text' | 'number' | 'toggle' | 'select'
  description: string
  min?: number
  max?: number
  options?: string[]
}

interface SectionDef {
  title: string
  icon: React.ComponentType<{ size?: number; className?: string }>
  fields: FieldDef[]
}

const SECTIONS: SectionDef[] = [
  {
    title: 'General',
    icon: Settings,
    fields: [
      { key: 'node_id', label: 'Node Name', type: 'text', description: 'Friendly name for this machine' },
      { key: 'sync_folder', label: 'Sync Folder', type: 'text', description: 'Local folder to keep in sync' },
      { key: 'syncignore_path', label: 'Ignore File Path', type: 'text', description: 'Path to .syncignore rules file' },
    ],
  },
  {
    title: 'Network',
    icon: Globe,
    fields: [
      { key: 'server_url', label: 'Server URL', type: 'text', description: 'Public-facing URL of this node' },
      { key: 'port', label: 'Port', type: 'number', description: 'HTTPS port (restart required)', min: 1, max: 65535 },
      { key: 'peers', label: 'Static Peers', type: 'text', description: 'Comma-separated peer URLs loaded at startup' },
      { key: 'max_peers', label: 'Max Peers', type: 'number', description: 'Maximum number of connected peers', min: 1, max: 100 },
    ],
  },
  {
    title: 'Security',
    icon: Shield,
    fields: [
      { key: 'verify_tls', label: 'Verify TLS Certificates', type: 'toggle', description: 'Validate peer TLS certificates (enable for production)' },
      { key: 'ssl_cert', label: 'SSL Certificate Path', type: 'text', description: 'Path to TLS certificate file (restart required)' },
      { key: 'ssl_key', label: 'SSL Key Path', type: 'text', description: 'Path to TLS private key file (restart required)' },
    ],
  },
  {
    title: 'Advanced',
    icon: Wrench,
    fields: [
      { key: 'log_level', label: 'Log Level', type: 'select', description: 'Logging verbosity level', options: ['DEBUG', 'INFO', 'WARNING', 'ERROR'] },
      { key: 'max_upload_mb', label: 'Max Upload Size (MB)', type: 'number', description: 'Maximum file upload size in megabytes', min: 1, max: 10000 },
      { key: 'db_path', label: 'Database Path', type: 'text', description: 'Path to the SQLite database file' },
      { key: 'debug', label: 'Debug Mode', type: 'toggle', description: 'Enable verbose debug output' },
    ],
  },
]

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['config'], queryFn: api.getConfig })
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [restartBanner, setRestartBanner] = useState(false)
  const [saved, setSaved] = useState(false)
  const [showToken, setShowToken] = useState(false)
  const [adminToken, setAdminToken] = useState<string | null>(null)
  const [tokenCopied, setTokenCopied] = useState(false)
  const [tokenLoading, setTokenLoading] = useState(false)

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

  async function revealToken() {
    if (adminToken) {
      setShowToken(!showToken)
      return
    }
    setTokenLoading(true)
    try {
      const res = await api.getAdminTokenFromServer()
      setAdminToken(res.admin_token)
      setShowToken(true)
    } catch { /* ignore */ } finally {
      setTokenLoading(false)
    }
  }

  function copyToken() {
    if (adminToken) {
      navigator.clipboard.writeText(adminToken)
      setTokenCopied(true)
      setTimeout(() => setTokenCopied(false), 2000)
    }
  }

  if (isLoading || !data) return <p className="text-gray-500 p-8">Loading…</p>

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (Object.keys(form).length > 0) save.mutate(form)
  }

  function getValue(key: string): unknown {
    return key in form ? form[key] : data![key]
  }

  function setField(key: string, value: unknown) {
    setForm(prev => ({ ...prev, [key]: value }))
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

      <form onSubmit={handleSubmit} className="space-y-6 max-w-2xl">
        {/* Admin Token Card */}
        <div className="bg-white rounded-xl shadow p-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-1 flex items-center gap-2">
            <Shield size={16} className="text-blue-600" /> Admin Token
          </h3>
          <p className="text-xs text-gray-500 mb-3">Use this token to log into the web UI from other devices or browsers.</p>
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-gray-50 border rounded-lg px-3 py-2 text-sm font-mono truncate">
              {showToken && adminToken ? adminToken : '••••••••••••••••••••••••'}
            </div>
            <button
              type="button"
              onClick={revealToken}
              disabled={tokenLoading}
              className="border rounded-lg p-2 hover:bg-gray-50 disabled:opacity-50"
              title={showToken ? 'Hide' : 'Reveal'}
            >
              {showToken ? <EyeOff size={16} className="text-gray-500" /> : <Eye size={16} className="text-gray-500" />}
            </button>
            {adminToken && (
              <button type="button" onClick={copyToken} className="border rounded-lg p-2 hover:bg-gray-50" title="Copy to clipboard">
                {tokenCopied ? <Check size={16} className="text-green-600" /> : <Copy size={16} className="text-gray-500" />}
              </button>
            )}
          </div>
        </div>

        {/* Setting Sections */}
        {SECTIONS.map(section => {
          const Icon = section.icon
          return (
            <div key={section.title} className="bg-white rounded-xl shadow p-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <Icon size={16} className="text-blue-600" /> {section.title}
              </h3>
              <div className="space-y-4">
                {section.fields.map(field => {
                  const val = getValue(field.key)

                  if (field.type === 'toggle') {
                    const checked = val === true || val === 'true' || val === 'True'
                    return (
                      <div key={field.key} className="flex items-center justify-between">
                        <div>
                          <label className="text-sm font-medium text-gray-700">{field.label}</label>
                          <p className="text-xs text-gray-400">{field.description}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => setField(field.key, !checked)}
                          className={`relative w-11 h-6 rounded-full transition-colors ${checked ? 'bg-blue-600' : 'bg-gray-300'}`}
                        >
                          <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${checked ? 'translate-x-5' : ''}`} />
                        </button>
                      </div>
                    )
                  }

                  if (field.type === 'select') {
                    return (
                      <div key={field.key}>
                        <label className="block text-sm font-medium text-gray-700 mb-1">{field.label}</label>
                        <select
                          className="w-full border rounded-lg px-3 py-2 text-sm bg-white"
                          value={String(val ?? '')}
                          onChange={e => setField(field.key, e.target.value)}
                        >
                          {field.options?.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                        </select>
                        <p className="text-xs text-gray-400 mt-1">{field.description}</p>
                      </div>
                    )
                  }

                  return (
                    <div key={field.key}>
                      <label className="block text-sm font-medium text-gray-700 mb-1">{field.label}</label>
                      <input
                        type={field.type}
                        className="w-full border rounded-lg px-3 py-2 text-sm"
                        value={String(val ?? '')}
                        onChange={e => setField(field.key, field.type === 'number' ? Number(e.target.value) : e.target.value)}
                        min={field.min}
                        max={field.max}
                      />
                      <p className="text-xs text-gray-400 mt-1">{field.description}</p>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}

        <button
          type="submit"
          disabled={Object.keys(form).length === 0}
          className="flex items-center gap-2 bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          <Save size={16} /> Save Changes
        </button>
      </form>
    </div>
  )
}
