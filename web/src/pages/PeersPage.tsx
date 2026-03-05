import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Plus, Trash2, Wifi, WifiOff, X, Ticket, Radar, Copy, Check, Link } from 'lucide-react'

export default function PeersPage() {
  const qc = useQueryClient()
  const { data = [], isLoading } = useQuery({ queryKey: ['peers'], queryFn: api.getPeers, refetchInterval: 10000 })
  const [showModal, setShowModal] = useState(false)

  const remove = useMutation({
    mutationFn: (url: string) => api.removePeer(url),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['peers'] }),
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Peers</h2>
        <button
          onClick={() => setShowModal(true)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm flex items-center gap-1.5 hover:bg-blue-700"
        >
          <Plus size={16} /> Add Peer
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

      {showModal && (
        <AddPeerModal onClose={() => { setShowModal(false); qc.invalidateQueries({ queryKey: ['peers'] }) }} />
      )}
    </div>
  )
}

function AddPeerModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'invite' | 'manual' | 'discover'>('invite')

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <h3 className="text-lg font-bold">Add Peer</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>

        <div className="flex border-b px-6">
          {([
            { id: 'invite' as const, icon: Ticket, label: 'Invite Code' },
            { id: 'manual' as const, icon: Link, label: 'Manual URL' },
            { id: 'discover' as const, icon: Radar, label: 'LAN Discovery' },
          ]).map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition ${
                tab === t.id ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <t.icon size={15} /> {t.label}
            </button>
          ))}
        </div>

        <div className="p-6">
          {tab === 'invite' && <InviteTab onClose={onClose} />}
          {tab === 'manual' && <ManualTab onClose={onClose} />}
          {tab === 'discover' && <DiscoverTab onClose={onClose} />}
        </div>
      </div>
    </div>
  )
}

function InviteTab({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<'choose' | 'generate' | 'accept'>('choose')
  const [inviteCode, setInviteCode] = useState('')
  const [acceptCode, setAcceptCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [copied, setCopied] = useState(false)

  async function handleGenerate() {
    setLoading(true)
    setError('')
    try {
      const res = await api.generateInvite()
      setInviteCode(res.invite_code)
      setMode('generate')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleAccept() {
    setLoading(true)
    setError('')
    try {
      const res = await api.acceptInvite(acceptCode.trim())
      setSuccess(`Connected to ${res.peer_node_id} at ${res.peer_url}${res.mutual ? ' (mutual)' : ''}`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  function copyCode() {
    navigator.clipboard.writeText(inviteCode)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (mode === 'choose') {
    return (
      <div className="space-y-3">
        <p className="text-sm text-gray-600 mb-4">
          Invite codes let you connect two nodes without manually sharing URLs or API keys.
        </p>
        <button
          onClick={handleGenerate}
          disabled={loading}
          className="w-full border-2 border-dashed border-gray-300 rounded-lg p-4 text-left hover:border-blue-400 hover:bg-blue-50 transition"
        >
          <div className="font-medium text-gray-900">Generate an invite code</div>
          <div className="text-xs text-gray-500 mt-1">Create a code to send to another node</div>
        </button>
        <button
          onClick={() => setMode('accept')}
          className="w-full border-2 border-dashed border-gray-300 rounded-lg p-4 text-left hover:border-blue-400 hover:bg-blue-50 transition"
        >
          <div className="font-medium text-gray-900">I have an invite code</div>
          <div className="text-xs text-gray-500 mt-1">Paste a code received from another node</div>
        </button>
      </div>
    )
  }

  if (mode === 'generate') {
    return (
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          Share this code with the other node. It expires in 1 hour.
        </p>
        <div className="relative">
          <textarea
            readOnly
            value={inviteCode}
            className="w-full border rounded-lg px-3 py-2.5 text-xs font-mono bg-gray-50 h-20 resize-none"
          />
          <button
            onClick={copyCode}
            className="absolute top-2 right-2 bg-white border rounded-md p-1.5 hover:bg-gray-50"
          >
            {copied ? <Check size={14} className="text-green-600" /> : <Copy size={14} className="text-gray-500" />}
          </button>
        </div>
        <p className="text-xs text-gray-400">
          On the other node, go to Peers &rarr; Add Peer &rarr; Invite Code &rarr; &ldquo;I have an invite code&rdquo; and paste this.
        </p>
        <button onClick={onClose} className="w-full bg-gray-100 text-gray-700 py-2.5 rounded-lg text-sm hover:bg-gray-200">
          Done
        </button>
      </div>
    )
  }

  // mode === 'accept'
  return (
    <div className="space-y-4">
      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-lg text-sm">{error}</div>}
      {success ? (
        <>
          <div className="bg-green-50 border border-green-200 text-green-700 px-3 py-2 rounded-lg text-sm">{success}</div>
          <button onClick={onClose} className="w-full bg-blue-600 text-white py-2.5 rounded-lg text-sm hover:bg-blue-700">
            Done
          </button>
        </>
      ) : (
        <>
          <p className="text-sm text-gray-600">Paste the invite code from the other node:</p>
          <textarea
            value={acceptCode}
            onChange={e => setAcceptCode(e.target.value)}
            className="w-full border rounded-lg px-3 py-2.5 text-xs font-mono h-20 resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
            placeholder="Paste invite code here…"
          />
          <button
            onClick={handleAccept}
            disabled={loading || !acceptCode.trim()}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Connecting…' : 'Connect'}
          </button>
        </>
      )}
    </div>
  )
}

function ManualTab({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function handleAdd() {
    setLoading(true)
    setError('')
    try {
      await api.addPeer(url.trim())
      setSuccess(`Peer added: ${url.trim()}`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Enter the full URL of the peer. Both nodes must share the same API key.
      </p>
      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-lg text-sm">{error}</div>}
      {success ? (
        <>
          <div className="bg-green-50 border border-green-200 text-green-700 px-3 py-2 rounded-lg text-sm">{success}</div>
          <button onClick={onClose} className="w-full bg-blue-600 text-white py-2.5 rounded-lg text-sm hover:bg-blue-700">
            Done
          </button>
        </>
      ) : (
        <>
          <input
            className="w-full border rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
            placeholder="https://192.168.1.10:8443"
            value={url}
            onChange={e => setUrl(e.target.value)}
          />
          <button
            onClick={handleAdd}
            disabled={loading || !url.trim()}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Adding…' : 'Add Peer'}
          </button>
        </>
      )}
    </div>
  )
}

function DiscoverTab({ onClose: _onClose }: { onClose: () => void }) {
  const { data = [], isLoading, refetch } = useQuery({
    queryKey: ['discover'],
    queryFn: api.discoverPeers,
    refetchInterval: 5000,
  })
  const [adding, setAdding] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  async function handleAdd(url: string) {
    setAdding(url)
    setError('')
    try {
      await api.addPeer(url)
      setSuccess(`Connected to ${url}`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setAdding(null)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        SyncCore nodes discovered on your local network. Make sure both nodes share the same API key, or use an invite code instead.
      </p>
      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-lg text-sm">{error}</div>}
      {success && <div className="bg-green-50 border border-green-200 text-green-700 px-3 py-2 rounded-lg text-sm">{success}</div>}
      {isLoading ? (
        <p className="text-sm text-gray-400 text-center py-6">Scanning…</p>
      ) : data.length === 0 ? (
        <div className="text-center py-8">
          <Radar size={32} className="text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-400">No nodes found on the local network.</p>
          <p className="text-xs text-gray-400 mt-1">Ensure other SyncCore nodes are running on the same network.</p>
          <button onClick={() => refetch()} className="text-blue-600 text-sm mt-3 hover:underline">
            Scan again
          </button>
        </div>
      ) : (
        <div className="divide-y border rounded-lg">
          {data.map(p => (
            <div key={p.url} className="flex items-center justify-between px-4 py-3">
              <div>
                <div className="text-sm font-medium">{p.node_id}</div>
                <div className="text-xs text-gray-500 font-mono">{p.url}</div>
                <div className="text-xs text-gray-400">IP: {p.ip}</div>
              </div>
              <button
                onClick={() => handleAdd(p.url)}
                disabled={adding === p.url}
                className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-xs hover:bg-blue-700 disabled:opacity-50"
              >
                {adding === p.url ? 'Adding…' : 'Connect'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
