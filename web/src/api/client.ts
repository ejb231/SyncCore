import type {
  StatusResponse, ConfigResponse, FileEntry, Conflict, Peer, QueueTask, LogEntry, SetupPayload,
  TrustListResponse, IdentityResponse, AddPeerResponse, ApprovePeerResponse,
} from './types'

let adminToken = localStorage.getItem('adminToken') || ''
let _onAuthFailure: (() => void) | null = null

export function setAdminToken(token: string) {
  adminToken = token
  localStorage.setItem('adminToken', token)
}

export function clearAdminToken() {
  adminToken = ''
  localStorage.removeItem('adminToken')
}

export function getAdminToken(): string {
  return adminToken
}

/** Register a callback invoked when the server rejects our admin token. */
export function onAuthFailure(cb: () => void) {
  _onAuthFailure = cb
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  }
  if (adminToken) {
    headers['Authorization'] = `Bearer ${adminToken}`
  }
  if (!(options.body instanceof FormData) && options.method !== 'GET' && options.body) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(path, { ...options, headers })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    // Stale or invalid admin token — clear it and notify the app so it
    // can redirect back to the setup / login page.
    if (res.status === 401 && adminToken) {
      clearAdminToken()
      _onAuthFailure?.()
    }
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  getStatus: () => request<StatusResponse>('/api/v1/status'),
  getConfig: () => request<ConfigResponse>('/api/v1/config'),
  putConfig: (data: Record<string, unknown>) =>
    request<{ updated: string[]; restart_required: boolean }>('/api/v1/config', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  getFiles: (search?: string) => {
    const q = search ? `?search=${encodeURIComponent(search)}` : ''
    return request<FileEntry[]>(`/api/v1/files${q}`)
  },
  getConflicts: () => request<Conflict[]>('/api/v1/conflicts'),
  resolveConflict: (id: number, deleteFile = false) =>
    request<{ status: string }>(`/api/v1/conflicts/${id}/resolve?delete_file=${deleteFile}`, { method: 'POST' }),
  getQueue: () => request<QueueTask[]>('/api/v1/queue'),
  retryTask: (id: number) => request<{ status: string }>(`/api/v1/queue/${id}/retry`, { method: 'POST' }),
  clearQueue: () => request<{ status: string; count: number }>('/api/v1/queue', { method: 'DELETE' }),
  pauseQueue: () => request<{ status: string }>('/api/v1/queue/pause', { method: 'POST' }),
  resumeQueue: () => request<{ status: string }>('/api/v1/queue/resume', { method: 'POST' }),
  getPeers: () => request<Peer[]>('/api/v1/peers'),
  addPeer: (url: string, node_id?: string) =>
    request<AddPeerResponse>('/api/v1/peers', { method: 'POST', body: JSON.stringify({ url, node_id }) }),
  removePeer: (url: string) =>
    request<{ status: string }>(`/api/v1/peers?url=${encodeURIComponent(url)}`, { method: 'DELETE' }),
  getIgnore: () => request<{ content: string }>('/api/v1/ignore'),
  putIgnore: (content: string) =>
    request<{ status: string }>('/api/v1/ignore', { method: 'PUT', body: JSON.stringify({ content }) }),
  getLogs: (level?: string) => {
    const q = level ? `?level=${encodeURIComponent(level)}` : ''
    return request<LogEntry[]>(`/api/v1/logs${q}`)
  },
  setup: (payload: SetupPayload) =>
    request<{ status: string; node_id: string; admin_token: string; device_id: string | null }>('/api/v1/setup', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  login: (username: string, password: string) =>
    request<{ status: string; node_id: string; token: string }>('/api/v1/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  // Trust management (certificate-based peer identity)
  getTrust: () =>
    request<TrustListResponse>('/api/v1/trust'),
  getIdentity: () =>
    request<IdentityResponse>('/api/v1/trust/identity'),
  approvePeer: (device_id: string) =>
    request<ApprovePeerResponse>('/api/v1/trust/approve', {
      method: 'POST',
      body: JSON.stringify({ device_id }),
    }),
  rejectPeer: (device_id: string) =>
    request<{ status: string }>('/api/v1/trust/reject', {
      method: 'POST',
      body: JSON.stringify({ device_id }),
    }),
  revokeTrust: (device_id: string) =>
    request<{ status: string }>(`/api/v1/trust?device_id=${encodeURIComponent(device_id)}`, { method: 'DELETE' }),
  getAdminTokenFromServer: () =>
    request<{ admin_token: string }>('/api/v1/admin-token'),
  changePassword: (current_password: string, new_password: string, new_username?: string) =>
    request<{ status: string }>('/api/v1/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password, ...(new_username ? { new_username } : {}) }),
    }),
  discoverPeers: () =>
    request<{ url: string; node_id: string; device_id: string; ip: string; last_seen: number }[]>('/api/v1/discover'),
}
