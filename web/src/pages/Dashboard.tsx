import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Activity, FileText, ListTodo, Users, Clock, ShieldCheck, ShieldAlert, Fingerprint } from 'lucide-react'

function Card({ icon: Icon, label, value, color }: { icon: typeof Activity; label: string; value: string | number; color: string }) {
  return (
    <div className="bg-white rounded-xl shadow p-5 flex items-center gap-4">
      <div className={`p-3 rounded-lg ${color}`}><Icon size={24} className="text-white" /></div>
      <div>
        <div className="text-sm text-gray-500">{label}</div>
        <div className="text-2xl font-semibold">{value}</div>
      </div>
    </div>
  )
}

function fmt(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export default function Dashboard() {
  const { data, isLoading, error } = useQuery({ queryKey: ['status'], queryFn: api.getStatus, refetchInterval: 5000 })

  if (isLoading) return <p className="p-8 text-gray-500">Loading…</p>
  if (error) return <p className="p-8 text-red-500">Error: {(error as Error).message}</p>
  if (!data) return null

  const status = data.pending_queue === 0 ? 'Synced' : data.pending_queue < 5 ? 'Syncing' : 'Busy'
  const statusColor = status === 'Synced' ? 'bg-green-500' : status === 'Syncing' ? 'bg-yellow-500' : 'bg-red-500'

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Dashboard</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <Card icon={Activity} label="Status" value={status} color={statusColor} />
        <Card icon={FileText} label="Indexed Files" value={data.indexed_files} color="bg-blue-500" />
        <Card icon={ListTodo} label="Queue Depth" value={data.pending_queue} color="bg-purple-500" />
        <Card icon={ShieldCheck} label="Trusted Peers" value={data.trusted_peers} color="bg-teal-500" />
      </div>
      <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        <Card icon={Users} label="Active Peers" value={data.peer_count} color="bg-cyan-500" />
        {data.pending_approvals > 0 && (
          <Card icon={ShieldAlert} label="Pending Approvals" value={data.pending_approvals} color="bg-amber-500" />
        )}
      </div>
      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div className="bg-white rounded-xl shadow p-5">
          <div className="text-sm text-gray-500 mb-1">Node ID</div>
          <div className="font-mono text-lg">{data.node_id}</div>
        </div>
        <div className="bg-white rounded-xl shadow p-5 flex items-center gap-3">
          <Clock size={20} className="text-gray-400" />
          <div>
            <div className="text-sm text-gray-500">Uptime</div>
            <div className="font-semibold">{fmt(data.uptime)}</div>
          </div>
        </div>
      </div>
      {data.device_id && (
        <div className="mt-5 bg-white rounded-xl shadow p-5">
          <div className="flex items-center gap-2 mb-1">
            <Fingerprint size={16} className="text-blue-500" />
            <div className="text-sm text-gray-500">Device ID</div>
          </div>
          <div className="font-mono text-sm tracking-wider text-gray-800">{data.device_id}</div>
          <p className="text-xs text-gray-400 mt-1">
            This is your node's unique identity — share it with peers so they can verify this device.
          </p>
        </div>
      )}
    </div>
  )
}
