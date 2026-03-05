# SyncCore

**Keep folders in sync across your machines — automatically, securely, with zero configuration.**

SyncCore is a peer-to-peer file synchronisation tool with a built-in web dashboard. Drop files into a folder on one machine and they appear on all the others. Everything is encrypted over TLS, everything runs from a single command.

---

## Quick Start (prebuilt binary)

Download the latest release for your platform from the [Releases](https://github.com/ejb231/SyncCore/releases) page, unzip, and run:

```bash
./SyncCore          # macOS / Linux
SyncCore.exe        # Windows
```

No Python or Node.js required.

---

## Quick Start (from source)

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
- Generate a secure configuration file (`.env`) with random API key, admin token, and node ID
- Create self-signed TLS certificates automatically (no OpenSSL needed)
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
| `python main.py --version` | Show version and exit |

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
| `MAX_UPLOAD_MB` | `500` | Maximum file size accepted per upload (in MB) |
| `VERIFY_TLS` | `false` | Set to `true` to require valid TLS certificates between peers |
| `DEBUG` | `false` | Enable CORS and extra debug logging |

### .syncignore

SyncCore ships with a `.syncignore` file that works like `.gitignore`. Patterns listed in it are excluded from syncing. Defaults include temp files, OS metadata, logs, and SyncCore's own internal files (database, certificates, `.env`). Edit it via the dashboard's **Settings** page or directly on disk.

---

## How It Works

1. **Watcher** monitors your sync folder for file changes in real time
2. Changes are queued in a local SQLite database (WAL mode)
3. A **queue worker** sends each change to all connected peers over HTTPS with exponential backoff on failure
4. On startup, an **initial scan** detects changes made while SyncCore was offline, and a **peer reconciliation** phase pulls any files that appeared on peers in the meantime
5. If the same file was edited on two machines, a **conflict copy** is created and both versions are kept
6. File renames are detected (via hash matching) to avoid unnecessary delete + re-upload cycles
7. The **web dashboard** shows you everything in real time via WebSocket

```
python main.py run
├── HTTPS Server (FastAPI + Uvicorn)
│   ├── File sync endpoints (upload / download / delete / index)
│   ├── Management API (/api/v1/*)
│   ├── WebSocket for real-time updates
│   └── Web dashboard (served from web/dist/)
├── File Watcher (Watchdog)
│   └── Detects changes → pushes to sync queue
├── Queue Worker
│   └── Processes queue → uploads to peers (with retry + backoff)
├── Peer Manager
│   └── Health-checks connected nodes
└── Sync Engine
    └── Initial scan + peer reconciliation on startup
```

---

## Security

- **TLS everywhere** — all peer communication uses HTTPS with auto-generated self-signed certificates. Set `VERIFY_TLS=true` when all nodes share a CA for full certificate validation.
- **API key authentication** — every sync request requires a shared `API_KEY` header.
- **Admin token** — the web dashboard and management API require a separate `ADMIN_TOKEN`. It is printed in full only on first run, then truncated in logs.
- **Constant-time auth** — all token/key comparisons use `hmac.compare_digest` to prevent timing attacks.
- **Private key protection** — TLS private keys are restricted to the current user (icacls on Windows, chmod 600 on Unix).
- **Upload rate limiting** — 60 uploads per minute per IP to prevent abuse.
- **Path traversal protection** — all file endpoints validate that resolved paths stay within the sync folder.
- **Atomic writes** — files are written to a temporary `.synctmp` file then atomically renamed, preventing partial reads.

---

## Connecting Two Machines

1. Install and start SyncCore on both machines
2. On Machine A, go to **Peers** in the dashboard and add Machine B's URL (e.g. `https://192.168.1.10:8443`)
3. Machine B will automatically appear. Files will start syncing in both directions.

Both machines must use the **same API key**. Set it in the `.env` file or through the dashboard before connecting.

---

## Running Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

---

## Building from Source

To create a standalone executable (no Python required for end users):

```bash
pip install pyinstaller
cd web && npm ci && npm run build && cd ..
pyinstaller synccore.spec --noconfirm --clean
```

The output is in `dist/SyncCore/`. Zip that folder and share it.

---

## Project Layout

```
SyncCore/
├── main.py                # CLI — run, status, reset
├── config.py              # Settings and .env management
├── requirements.txt       # Python dependencies
├── synccore.spec          # PyInstaller build spec
├── .syncignore            # Default file exclusion patterns
├── core/
│   ├── server.py          # HTTPS server + sync API + WebSocket
│   ├── client.py          # Sync client (uploads/downloads to/from peers)
│   ├── engine.py          # Initial scan + peer reconciliation
│   ├── watcher.py         # Real-time file-system monitor
│   ├── queue_worker.py    # Background task processor with retry
│   ├── peer_manager.py    # Peer registry + health checks
│   ├── management_api.py  # Management REST API
│   ├── orchestrator.py    # Component lifecycle + supervised threads
│   └── ws.py              # WebSocket manager
├── utils/
│   ├── auth.py            # Authentication middleware
│   ├── certs.py           # TLS certificate generation
│   ├── file_index.py      # SQLite database (file index, queue, conflicts)
│   ├── file_ops.py        # Hashing + gzip compression
│   ├── filters.py         # .syncignore pattern matching
│   ├── conflict.py        # Conflict resolution
│   ├── logging.py         # Logging setup
│   ├── paths.py           # Path validation
│   └── resilience.py      # Supervised threads, atomic writes, rename detection
├── web/                   # React 19 + TypeScript dashboard
│   ├── src/               # Source (TailwindCSS, TanStack Query, React Router)
│   └── dist/              # Production build (git-ignored, built by CI)
└── tests/
    └── test_sync.py       # 79 tests
```
