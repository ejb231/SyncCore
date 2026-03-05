// API response types

export interface StatusResponse {
  node_id: string
  sync_folder: string
  port: number
  peer_count: number
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
  api_key: string
  node_id: string
  peers: string
}

export interface WSEvent {
  event: 'file_uploaded' | 'file_deleted' | 'conflict' | 'peer_registered' | 'log'
  data: Record<string, unknown>
}
