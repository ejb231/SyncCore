import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import {
  Plus, Trash2, Wifi, WifiOff, X, Radar, Link, ShieldCheck, ShieldAlert,
  ShieldX, CheckCircle2, XCircle, Fingerprint,
} from 'lucide-react'

export default function PeersPage() {
  const qc = useQueryClient()
  const { data: peers = [], isLoading: peersLoading } = useQuery({ queryKey: ['peers'], queryFn: api.getPeers, refetchInterval: 10000 })
  const { data: trust } = useQuery({ queryKey: ['trust'], queryFn: api.getTrust, refetchInterval: 5000 })
  const [showModal, setShowModal] = useState(false)

  const remove = useMutation({
    mutationFn: (url: string) => api.removePeer(url),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['peers'] }),
  })

  const pendingCount = trust?.pending?.length ?? 0

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

      {/* Pending approval banner */}
      {pendingCount > 0 && (
        <PendingApprovals
          pending={trust!.pending}
          onAction={() => qc.invalidateQueries({ queryKey: ['trust', 'peers'] })}
        />
      )}

      {/* Trusted Peers */}
      {trust && trust.trusted.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <ShieldCheck size={14} /> Trusted Devices
          </h3>
          <div className="bg-white rounded-xl shadow overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="text-left px-4 py-3">Node</th>
                  <th className="text-left px-4 py-3">Device ID</th>
                  <th className="text-left px-4 py-3">URL</th>
                  <th className="text-left px-4 py-3">Approved</th>
                  <th className="text-left px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {trust.trusted.map(p => (
                  <TrustedRow key={p.device_id} peer={p} onRevoke={() => qc.invalidateQueries({ queryKey: ['trust', 'peers'] })} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Active connections table */}
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
        <Wifi size={14} /> Active Connections
      </h3>
      {peersLoading ? <p className="text-gray-500">Loading…</p> : (
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
              {peers.map(p => (
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
              {peers.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No peers connected</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <AddPeerModal onClose={() => { setShowModal(false); qc.invalidateQueries({ queryKey: ['peers', 'trust'] }) }} />
      )}
    </div>
  )
}

function TrustedRow({ peer, onRevoke }: { peer: { device_id: string; url: string; node_id: string; approved_at: number }; onRevoke: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleRevoke() {
    setLoading(true)
    try {
      await api.revokeTrust(peer.device_id)
      onRevoke()
    } finally {
      setLoading(false)
      setConfirming(false)
    }
  }

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-2 font-medium">{peer.node_id}</td>
      <td className="px-4 py-2 font-mono text-xs text-gray-500">{peer.device_id}</td>
      <td className="px-4 py-2 font-mono text-xs">{peer.url}</td>
      <td className="px-4 py-2 text-gray-500">{new Date(peer.approved_at * 1000).toLocaleDateString()}</td>
      <td className="px-4 py-2">
        {confirming ? (
          <div className="flex items-center gap-1">
            <button onClick={handleRevoke} disabled={loading} className="text-red-600 text-xs font-medium hover:underline">
              Confirm
            </button>
            <button onClick={() => setConfirming(false)} className="text-gray-400 text-xs hover:underline ml-1">
              Cancel
            </button>
          </div>
        ) : (
          <button onClick={() => setConfirming(true)} className="text-red-600 hover:bg-red-50 p-1 rounded" title="Revoke trust">
            <ShieldX size={16} />
          </button>
        )}
      </td>
    </tr>
  )
}

function PendingApprovals({ pending, onAction }: { pending: { device_id: string; url: string; node_id: string; requested_at: number }[]; onAction: () => void }) {
  return (
    <div className="mb-6 bg-amber-50 border border-amber-200 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-amber-800 mb-3 flex items-center gap-1.5">
        <ShieldAlert size={16} /> Pending Pairing Requests ({pending.length})
      </h3>
      <div className="space-y-3">
        {pending.map(p => (
          <PendingRow key={p.device_id} peer={p} onAction={onAction} />
        ))}
      </div>
    </div>
  )
}

function PendingRow({ peer, onAction }: { peer: { device_id: string; url: string; node_id: string; requested_at: number }; onAction: () => void }) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState('')

  async function handleApprove() {
    setLoading(true)
    try {
      const res = await api.approvePeer(peer.device_id)
      setResult(res.mutual ? 'Approved — mutual trust established!' : `Approved — ${res.mutual_message}`)
      onAction()
    } catch (err) {
      setResult(`Error: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleReject() {
    setLoading(true)
    try {
      await api.rejectPeer(peer.device_id)
      onAction()
    } catch (err) {
      setResult(`Error: ${(err as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white rounded-lg border border-amber-200 p-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-medium text-gray-900">{peer.node_id}</div>
          <div className="text-xs font-mono text-gray-500 flex items-center gap-1 mt-0.5">
            <Fingerprint size={12} /> {peer.device_id}
          </div>
          <div className="text-xs text-gray-400 mt-0.5">{peer.url}</div>
        </div>
        {!result && (
          <div className="flex items-center gap-1.5 ml-3 shrink-0">
            <button
              onClick={handleApprove}
              disabled={loading}
              className="bg-green-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-green-700 disabled:opacity-50 flex items-center gap-1"
            >
              <CheckCircle2 size={14} /> Approve
            </button>
            <button
              onClick={handleReject}
              disabled={loading}
              className="bg-red-50 text-red-600 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-red-100 disabled:opacity-50 flex items-center gap-1"
            >
              <XCircle size={14} /> Reject
            </button>
          </div>
        )}
      </div>
      {result && <div className="text-xs text-green-700 mt-2">{result}</div>}
    </div>
  )
}

function AddPeerModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'manual' | 'discover'>('manual')

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 pt-5 pb-3">
          <h3 className="text-lg font-bold">Add Peer</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>

        <div className="flex border-b px-6">
          {([
            { id: 'manual' as const, icon: Link, label: 'Peer URL' },
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
          {tab === 'manual' && <ManualTab onClose={onClose} />}
          {tab === 'discover' && <DiscoverTab onClose={onClose} />}
        </div>
      </div>
    </div>
  )
}

function ManualTab({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [remoteInfo, setRemoteInfo] = useState<{ device_id: string; node_id: string } | null>(null)

  async function handleAdd() {
    setLoading(true)
    setError('')
    try {
      const res = await api.addPeer(url.trim())
      setRemoteInfo({ device_id: res.device_id, node_id: res.node_id })
      setSuccess(`Trusted ${res.node_id} (${res.device_id}). ${res.mutual_message}`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Enter the URL of the peer. Their identity will be fetched automatically and a pairing request will be sent.
      </p>
      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-lg text-sm">{error}</div>}
      {success ? (
        <>
          <div className="bg-green-50 border border-green-200 text-green-700 px-3 py-2 rounded-lg text-sm">{success}</div>
          {remoteInfo && (
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="text-xs text-gray-500">Remote Device ID</div>
              <div className="font-mono text-xs mt-0.5">{remoteInfo.device_id}</div>
            </div>
          )}
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
          <p className="text-xs text-gray-400">
            No API key needed — peers verify each other using certificate signatures.
          </p>
          <button
            onClick={handleAdd}
            disabled={loading || !url.trim()}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Connecting…' : 'Trust & Connect'}
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
      const res = await api.addPeer(url)
      setSuccess(`Trusted ${res.node_id ?? url}. ${res.mutual_message ?? ''}`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setAdding(null)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        SyncCore nodes discovered on your local network. Click <strong>Trust</strong> to add a peer — no shared keys needed.
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
                {p.device_id && (
                  <div className="text-xs text-gray-400 font-mono flex items-center gap-1 mt-0.5">
                    <Fingerprint size={10} /> {p.device_id}
                  </div>
                )}
                <div className="text-xs text-gray-400">IP: {p.ip}</div>
              </div>
              <button
                onClick={() => handleAdd(p.url)}
                disabled={adding === p.url}
                className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-xs hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
              >
                <ShieldCheck size={12} />
                {adding === p.url ? 'Adding…' : 'Trust'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
