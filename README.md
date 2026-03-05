# SyncCore

**Keep folders in sync across your machines — automatically, securely, with zero configuration.**

SyncCore is a peer-to-peer file synchronisation tool with a built-in web dashboard. Drop files into a folder on one machine and they appear on all the others. Peers authenticate using certificate-pinned signatures (TOFU model), discover each other automatically on the LAN, and all traffic is encrypted over TLS. Everything runs from a single command.

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
- Generate a secure configuration file (`.env`) with a random node ID
- Generate a 2048-bit RSA key pair and self-signed TLS certificate (no OpenSSL needed)
- Create a unique device identity (SHA-256 fingerprint of the certificate)
- Open your browser to the setup wizard

The setup wizard will ask you to choose a **username and password** for the web dashboard.

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
| `python main.py reset-password` | Reset the admin password when locked out |
| `python main.py --version` | Show version and exit |

---

## Web Dashboard

Open **https://localhost:8443** in your browser after starting SyncCore.

On first visit you'll see the **Setup** wizard to configure your sync folder and create your login credentials. After setup, sign in with your **username and password**.

| Page | What you can do |
|---|---|
| **Dashboard** | See sync status, file count, queue depth, peer count, uptime at a glance |
| **Files** | Browse and search all synced files |
| **Conflicts** | Resolve files that were edited on multiple machines at once |
| **Peers** | Discover, pair, approve, and revoke peer nodes |
| **Queue** | Watch pending sync tasks, retry failures, pause/resume processing |
| **Settings** | Change configuration, manage .syncignore, export device identity |
| **Logs** | Live, colour-coded log stream with level filtering |

---

## Configuration

All settings live in a `.env` file that is auto-generated on first run (file permissions are restricted to the current OS user). You can edit it by hand or through the web dashboard's **Settings** page.

| Setting | Default | What it controls |
|---|---|---|
| `SYNC_FOLDER` | `./data/sync_folder` | The folder on this machine that stays in sync |
| `PORT` | `8443` | HTTPS port the server listens on |
| `API_KEY` | *(auto-generated)* | Legacy shared secret (deprecated — use certificate pairing instead) |
| `NODE_ID` | *(auto-generated)* | A short name for this machine |
| `PEERS` | *(empty)* | Comma-separated URLs of other SyncCore nodes |
| `ADMIN_TOKEN` | *(auto-generated)* | Internal bearer token for API authentication (managed automatically) |
| `ADMIN_USERNAME` | `admin` | Username for the web dashboard login |
| `ADMIN_PASSWORD_HASH` | *(empty)* | PBKDF2-SHA256 hash of the admin password (set during setup) |
| `LOG_LEVEL` | `INFO` | How verbose the logs are (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `MAX_PEERS` | `20` | Maximum number of connected nodes |
| `MAX_UPLOAD_MB` | `500` | Maximum file size accepted per upload (in MB) |
| `VERIFY_TLS` | `false` | Set to `true` to require valid TLS certificates between peers |
| `DEBUG` | `false` | Enable extra debug logging |

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
7. **LAN discovery** automatically finds other SyncCore nodes on the local network via UDP multicast
8. The **web dashboard** shows you everything in real time via WebSocket

```
python main.py run
├── HTTPS Server (FastAPI + Uvicorn)
│   ├── File sync endpoints (upload / download / delete / index)
│   ├── Pairing endpoints (/pair/request, /pair/identity)
│   ├── Management API (/api/v1/*)
│   ├── WebSocket for real-time updates
│   └── Web dashboard (served from web/dist/)
├── File Watcher (Watchdog)
│   └── Detects changes → pushes to sync queue
├── Queue Worker
│   └── Processes queue → uploads to peers (with retry + backoff)
├── Peer Manager
│   └── Health-checks connected nodes
├── LAN Discovery
│   └── UDP multicast broadcast + listener for auto-discovery
├── Trust Store
│   └── Certificate-pinned peer identities (trusted_peers.json)
└── Sync Engine
    └── Initial scan + peer reconciliation on startup
```

---

## Security

- **Certificate-based authentication (TOFU)** — each node generates a unique RSA key pair. Peers authenticate by signing requests with their private key. The first time two nodes meet, you approve the pairing in the dashboard. After that, identity is verified cryptographically via the pinned public key — no shared secrets needed.
- **Trust store** — approved peer identities are stored in `trusted_peers.json`. You can revoke any peer at any time from the dashboard.
- **Request signing** — sync requests include `X-Device-ID`, `X-Timestamp`, and `X-Signature` headers. Signatures use RSA-PSS with a 5-minute timestamp window to prevent replay attacks.
- **TLS everywhere** — all peer communication uses HTTPS with auto-generated self-signed certificates. Set `VERIFY_TLS=true` when all nodes share a CA for full certificate validation.
- **Username/password login** — the web dashboard requires a username and password set during initial setup. Credentials are hashed with PBKDF2-SHA256 (600,000 iterations) before storage. An internal bearer token is used for API sessions but is never exposed to the user.
- **Constant-time auth** — all credential comparisons use `hmac.compare_digest` to prevent timing attacks.
- **Private key protection** — TLS private keys and `.env` are restricted to the current user (`icacls` on Windows, `chmod 600` on Unix).
- **Upload rate limiting** — 60 uploads per minute per IP to prevent abuse.
- **Gzip bomb protection** — decompressed uploads are capped at the configured `MAX_UPLOAD_MB`.
- **Path traversal protection** — all file endpoints validate that resolved paths stay within the sync folder.
- **Atomic writes** — files are written to a temporary `.synctmp` file then atomically renamed, preventing partial reads.
- **Graceful shutdown** — Ctrl+C cleanly shuts down the server, releases the port, stops all background threads, and closes the database.

---

## Connecting Two Machines

SyncCore uses a **trust-on-first-use (TOFU)** model — no shared API keys needed.

1. Install and start SyncCore on both machines
2. Both nodes will automatically discover each other if they're on the same LAN
3. On Machine A, go to **Peers** in the dashboard — Machine B will appear under "Discovered on LAN"
4. Click **Pair** next to Machine B. Machine A will trust Machine B immediately, and Machine B will see a pending approval request
5. On Machine B, go to **Peers** and click **Approve** to complete mutual trust
6. Files will start syncing in both directions

For machines on different networks, enter the URL manually (e.g. `https://192.168.1.10:8443`) in the Peers page.

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
│   ├── server.py          # HTTPS server + sync API + pairing + WebSocket
│   ├── client.py          # Sync client (signed uploads/downloads to/from peers)
│   ├── engine.py          # Initial scan + peer reconciliation
│   ├── watcher.py         # Real-time file-system monitor
│   ├── queue_worker.py    # Background task processor with retry
│   ├── peer_manager.py    # Peer registry + health checks
│   ├── management_api.py  # Management REST API + pairing endpoints
│   ├── orchestrator.py    # Component lifecycle + supervised threads
│   └── ws.py              # WebSocket manager
├── utils/
│   ├── auth.py            # Certificate signature + password auth
│   ├── certs.py           # TLS certs, RSA key pair, request signing
│   ├── trust_store.py     # Certificate-pinned peer trust store
│   ├── discovery.py       # LAN auto-discovery via UDP multicast
│   ├── file_index.py      # SQLite database (file index, queue, conflicts)
│   ├── file_ops.py        # Hashing + gzip compression
│   ├── filters.py         # .syncignore pattern matching
│   ├── conflict.py        # Conflict resolution
│   ├── logging.py         # Logging setup
│   ├── paths.py           # Path validation
│   └── resilience.py      # Supervised threads, atomic writes, rename detection
├── web/                   # React 19 + TypeScript dashboard
│   ├── src/               # Source (TailwindCSS, TanStack Query, React Router)
│   │   └── pages/         # Setup, Login, Dashboard, Files, Peers, etc.
│   └── dist/              # Production build (git-ignored, built by CI)
└── tests/
    └── test_sync.py       # Test suite
```
