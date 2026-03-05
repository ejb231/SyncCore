# SyncCore

**Keep folders in sync across your machines - automatically, securely, with zero configuration.**

SyncCore is a file synchronisation tool with a built-in web dashboard. Drop files into a folder on one machine and they appear on all the others. Everything is encrypted, everything runs from a single command.

---

## Getting Started

### 1. Install Python dependencies

```bash
cd SyncCore
pip install -r requirements.txt
```

### 2. Build the web dashboard (one time)

```bash
cd web
npm install
npm run build
cd ..
```

### 3. Run SyncCore

```bash
python main.py run
```

That's it. On first launch SyncCore will:
- Generate a secure configuration file (`.env`)
- Create TLS certificates automatically (no OpenSSL needed)
- Open your browser to the management dashboard

Your admin token and URL are printed in the terminal — use them to log in.

### Starting fresh

If you ever want to wipe the configuration and start over:

```bash
python main.py reset
python main.py run
```

---

## CLI Reference

| Command | What it does |
|---|---|
| `python main.py run` | Start SyncCore (server + sync client) |
| `python main.py run --server` | Run only the HTTPS server |
| `python main.py run --client` | Run only the file watcher + sync client |
| `python main.py run --no-browser` | Start without auto-opening the browser |
| `python main.py status` | Show node info and queue depth |
| `python main.py reset` | Delete config and certificates to start fresh |

---

## Web Dashboard

Open **https://localhost:8443** in your browser after starting SyncCore.

| Page | What you can do |
|---|---|
| **Dashboard** | See sync status, file count, queue depth, peer count, uptime at a glance |
| **Files** | Browse and search all synced files |
| **Conflicts** | Resolve files that were edited on multiple machines at once |
| **Peers** | Add or remove other SyncCore nodes |
| **Queue** | Watch pending sync tasks, retry failures, pause/resume processing |
| **Settings** | Change configuration without editing files |
| **Logs** | Live, colour-coded log stream with level filtering |

---

## Configuration

All settings live in a `.env` file that is auto-generated on first run. You can edit it by hand or through the web dashboard's **Settings** page.

| Setting | Default | What it controls |
|---|---|---|
| `SYNC_FOLDER` | `./data/sync_folder` | The folder on this machine that stays in sync |
| `PORT` | `8443` | HTTPS port the server listens on |
| `API_KEY` | *(auto-generated)* | Shared secret between nodes for sync auth |
| `NODE_ID` | *(auto-generated)* | A short name for this machine |
| `PEERS` | *(empty)* | Comma-separated URLs of other SyncCore nodes |
| `ADMIN_TOKEN` | *(auto-generated)* | Token for the web dashboard and management API |
| `LOG_LEVEL` | `INFO` | How verbose the logs are (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `MAX_PEERS` | `20` | Maximum number of connected nodes |

---

## How It Works

1. **Watcher** monitors your sync folder for changes
2. Changes are queued in a local SQLite database
3. A **queue worker** sends each change to all connected peers over HTTPS
4. If the same file was edited on two machines, a **conflict copy** is created and both versions are kept
5. The **web dashboard** shows you everything in real time via WebSocket

```
python main.py run
├── HTTPS Server (FastAPI + Uvicorn)
│   ├── File sync endpoints (upload / delete / index)
│   ├── Management API (/api/v1/*)
│   ├── WebSocket for real-time updates
│   └── Web dashboard (served from web/dist/)
├── File Watcher (Watchdog)
│   └── Detects changes → pushes to sync queue
├── Queue Worker
│   └── Processes queue → uploads to peers
└── Peer Manager
    └── Health-checks connected nodes
```

---

## Connecting Two Machines

1. Install and start SyncCore on both machines
2. On Machine A, go to **Peers** in the dashboard and add Machine B's URL (e.g. `https://192.168.1.10:8443`)
3. Machine B will automatically appear. Files will start syncing in both directions.

Both machines must use the **same API key**. Set it in the `.env` file or through the dashboard before connecting.

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Project Layout

```
SyncCore/
├── main.py                # CLI — run, status, reset
├── config.py              # Settings and .env management
├── requirements.txt       # Python dependencies
├── core/
│   ├── server.py          # HTTPS server + API + WebSocket
│   ├── client.py          # Sync client (uploads to peers)
│   ├── engine.py          # Initial folder scan
│   ├── watcher.py         # File-system monitor
│   ├── queue_worker.py    # Background task processor
│   ├── peer_manager.py    # Peer registry + health checks
│   ├── management_api.py  # Management REST API
│   ├── orchestrator.py    # Component lifecycle
│   └── ws.py              # WebSocket manager
├── utils/
│   ├── auth.py            # Authentication
│   ├── certs.py           # TLS certificate generation
│   ├── file_index.py      # SQLite database
│   ├── file_ops.py        # Hashing + compression
│   ├── filters.py         # .syncignore patterns
│   ├── conflict.py        # Conflict resolution
│   ├── logging.py         # Logging setup
│   └── paths.py           # Path validation
├── web/                   # React dashboard
│   ├── src/               # TypeScript source
│   └── dist/              # Production build
└── tests/
    └── test_sync.py       # Test suite
```
