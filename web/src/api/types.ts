// API response types

export interface StatusResponse {
  node_id: string
  device_id: string | null
  sync_folder: string
  port: number
  peer_count: number
  trusted_peers: number
  pending_approvals: number
  indexed_files: number
  pending_queue: number
  uptime: number
}

export interface ConfigResponse {
  [key: string]: string | number | boolean
}

export interface FileEntry {
  path: string
  hash: string
  mtime: number
  size: number
  origin: string
  version: number
}

export interface Conflict {
  id: number
  path: string
  conflict_file: string
  origin: string
  detected_at: number
  resolved: number
}

export interface Peer {
  url: string
  node_id: string
  alive: boolean
  last_seen: number
  failures: number
}

export interface TrustedPeer {
  device_id: string
  url: string
  node_id: string
  public_key_pem: string
  approved_at: number
  last_seen: number
}

export interface PendingPeer {
  device_id: string
  url: string
  node_id: string
  public_key_pem: string
  requested_at: number
}

export interface TrustListResponse {
  trusted: TrustedPeer[]
  pending: PendingPeer[]
}

export interface IdentityResponse {
  device_id: string
  node_id: string
  public_key_pem: string
}

export interface QueueTask {
  id: number
  action: string
  path: string
  abs_path: string | null
  attempts: number
  max_retries: number
  next_retry: number
  status: string
  created_at: number
  updated_at: number
}

export interface LogEntry {
  timestamp: number
  level: string
  name: string
  message: string
}

export interface SetupPayload {
  sync_folder: string
  node_id: string
  peers: string
}

export interface AddPeerResponse {
  status: string
  url: string
  device_id: string
  node_id: string
  mutual: boolean
  mutual_message: string
}

export interface ApprovePeerResponse {
  status: string
  mutual: boolean
  mutual_message: string
}

export interface WSEvent {
  event: 'file_uploaded' | 'file_deleted' | 'conflict' | 'peer_registered' | 'log'
  data: Record<string, unknown>
}
