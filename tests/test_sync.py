from __future__ import annotations

import time
from pathlib import Path

import pytest

from config import Settings, write_env
from utils.certs import ensure_certs, generate_self_signed_cert
from utils.conflict import make_conflict_name, resolve_conflict
from utils.file_index import Database
from utils.file_ops import (
    calculate_hash,
    compress,
    decompress,
    hash_bytes,
    should_compress,
)
from utils.filters import SyncIgnore


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp(tmp_path):
    return tmp_path


@pytest.fixture()
def db(tmp_path):
    return Database(str(tmp_path / "test.db"))


@pytest.fixture()
def settings(tmp_path):
    sync = tmp_path / "sync"
    sync.mkdir()
    return Settings(
        sync_folder=str(sync),
        db_path=str(tmp_path / "test.db"),
        api_key="test-key",
        node_id="test-node",
        port=19876,
        admin_token="test-admin-token",
        setup_complete=True,
    )


# ── file_ops ─────────────────────────────────────────────────────────────────


class TestFileOps:
    def test_calculate_hash_deterministic(self, tmp):
        f = tmp / "hello.txt"
        f.write_text("hello world")
        assert calculate_hash(f) == calculate_hash(f)

    def test_hash_bytes(self):
        data = b"test data"
        assert hash_bytes(data) == hash_bytes(data)
        assert len(hash_bytes(data)) == 64

    def test_compress_decompress_roundtrip(self):
        original = b"a" * 10000
        compressed = compress(original)
        assert len(compressed) < len(original)
        assert decompress(compressed) == original

    def test_should_compress(self):
        assert should_compress("readme.md", 2048) is True
        assert should_compress("photo.jpg", 2048) is False
        assert should_compress("tiny.txt", 100) is False


# ── filters ──────────────────────────────────────────────────────────────────


class TestSyncIgnore:
    def test_ignores_matching_pattern(self, tmp):
        ignore_file = tmp / ".syncignore"
        ignore_file.write_text("*.tmp\n__pycache__/\n")
        si = SyncIgnore(ignore_file)
        assert si.is_ignored("data.tmp") is True
        assert si.is_ignored("src/__pycache__/mod.pyc") is True
        assert si.is_ignored("readme.md") is False

    def test_empty_file(self, tmp):
        ignore_file = tmp / ".syncignore"
        ignore_file.write_text("")
        si = SyncIgnore(ignore_file)
        assert si.is_ignored("anything.py") is False

    def test_missing_file(self, tmp):
        si = SyncIgnore(tmp / "nonexistent")
        assert si.is_ignored("file.txt") is False


# ── database ─────────────────────────────────────────────────────────────────


class TestDatabase:
    def test_upsert_and_get(self, db):
        db.upsert_file("a/b.txt", "abc123", 1000.0, 42, origin="node-1")
        row = db.get_file("a/b.txt")
        assert row is not None
        assert row["hash"] == "abc123"
        assert row["origin"] == "node-1"

    def test_delete(self, db):
        db.upsert_file("x.txt", "h", 1.0, 1)
        db.delete_file("x.txt")
        assert db.get_file("x.txt") is None

    def test_all_files(self, db):
        db.upsert_file("a.py", "h1", 1.0, 10)
        db.upsert_file("b.py", "h2", 2.0, 20)
        assert len(db.all_files()) == 2

    def test_queue_push_deduplicates(self, db):
        id1 = db.push_task("upload", "f.txt", "/abs/f.txt")
        id2 = db.push_task("upload", "f.txt", "/abs/f.txt")
        assert id1 == id2

    def test_queue_pop_and_complete(self, db):
        db.push_task("delete", "old.txt")
        task = db.pop_task(time.time() + 1)
        assert task is not None
        assert task["action"] == "delete"
        db.complete_task(task["id"])
        assert db.pending_count() == 0

    def test_queue_fail_and_retry(self, db):
        db.push_task("upload", "retry.txt", "/abs/retry.txt")
        task = db.pop_task(time.time() + 1)
        db.fail_task(task["id"], time.time() + 100)
        assert db.pop_task(time.time()) is None
        task2 = db.pop_task(time.time() + 200)
        assert task2 is not None

    def test_file_count(self, db):
        assert db.file_count() == 0
        db.upsert_file("a.py", "h1", 1.0, 10)
        assert db.file_count() == 1

    def test_search_files(self, db):
        db.upsert_file("docs/readme.md", "h1", 1.0, 10)
        db.upsert_file("src/main.py", "h2", 2.0, 20)
        assert len(db.search_files("docs")) == 1
        assert len(db.search_files("main")) == 1
        assert len(db.search_files("nope")) == 0

    def test_all_tasks(self, db):
        db.push_task("upload", "a.txt", "/a")
        db.push_task("delete", "b.txt")
        tasks = db.all_tasks()
        assert len(tasks) == 2

    def test_clear_pending_tasks(self, db):
        db.push_task("upload", "a.txt", "/a")
        db.push_task("delete", "b.txt")
        cleared = db.clear_pending_tasks()
        assert cleared == 2
        assert db.pending_count() == 0

    def test_retry_task(self, db):
        db.push_task("upload", "rt.txt", "/rt")
        task = db.pop_task(time.time() + 1)
        db.fail_task(task["id"], time.time() + 9999)
        assert db.retry_task(task["id"]) is True
        t2 = db.pop_task(time.time() + 1)
        assert t2 is not None
        assert t2["attempts"] == 0


# ── conflict DB CRUD ─────────────────────────────────────────────────────────


class TestConflictDB:
    def test_record_and_list(self, db):
        cid = db.record_conflict("doc.txt", "doc (Conflict peer-1).txt", "peer-1")
        assert cid > 0
        conflicts = db.list_conflicts(resolved=False)
        assert len(conflicts) == 1
        assert conflicts[0]["path"] == "doc.txt"

    def test_resolve_conflict_record(self, db):
        cid = db.record_conflict("a.txt", "a_conflict.txt", "peer-2")
        assert db.resolve_conflict_record(cid) is True
        assert len(db.list_conflicts(resolved=False)) == 0
        assert len(db.list_conflicts(resolved=True)) == 1

    def test_resolve_nonexistent(self, db):
        assert db.resolve_conflict_record(9999) is False


# ── conflict resolver ────────────────────────────────────────────────────────


class TestConflictResolver:
    def test_conflict_name_format(self):
        name = make_conflict_name("report.txt", "node-2")
        assert "Conflict" in name
        assert "node-2" in name
        assert name.endswith(".txt")

    def test_resolve_conflict_creates_file(self, tmp):
        original = tmp / "doc.txt"
        original.write_text("version A")
        incoming = b"version B"
        result = resolve_conflict(original, incoming, hash_bytes(incoming), "peer-1")
        assert result.exists()
        assert result.read_bytes() == incoming
        assert original.read_text() == "version A"

    def test_resolve_conflict_with_db(self, tmp, db):
        original = tmp / "doc.txt"
        original.write_text("version A")
        incoming = b"version B"
        result = resolve_conflict(
            original, incoming, hash_bytes(incoming), "peer-1", db=db
        )
        assert result.exists()
        conflicts = db.list_conflicts(resolved=False)
        assert len(conflicts) == 1
        assert conflicts[0]["origin"] == "peer-1"


# ── server integration (uses TestClient) ─────────────────────────────────────


class TestServerEndpoints:
    @pytest.fixture(autouse=True)
    def setup_app(self, settings, db):
        from fastapi.testclient import TestClient
        from core.server import app

        app.state.settings = settings
        app.state.db = db
        self.client = TestClient(app)
        self.headers = {"x-api-key": "test-key"}
        self.settings = settings

    def test_health(self):
        r = self.client.get("/health")
        assert r.status_code == 200

    def test_upload_success(self):
        r = self.client.post(
            "/upload",
            data={"path": "hello.txt", "origin": "test-node", "compressed": "false"},
            files={"file": ("hello.txt", b"hello world")},
            headers=self.headers,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        dest = Path(self.settings.sync_folder) / "hello.txt"
        assert dest.read_bytes() == b"hello world"

    def test_upload_compressed(self):
        data = compress(b"compressed payload")
        r = self.client.post(
            "/upload",
            data={"path": "comp.txt", "origin": "n1", "compressed": "true"},
            files={"file": ("comp.txt", data)},
            headers=self.headers,
        )
        assert r.status_code == 200
        dest = Path(self.settings.sync_folder) / "comp.txt"
        assert dest.read_bytes() == b"compressed payload"

    def test_upload_rejects_bad_key(self):
        r = self.client.post(
            "/upload",
            data={"path": "x.txt", "origin": "n", "compressed": "false"},
            files={"file": ("x.txt", b"data")},
            headers={"x-api-key": "wrong"},
        )
        assert r.status_code == 403

    def test_upload_conflict_detection(self):
        dest = Path(self.settings.sync_folder) / "conflict.txt"
        dest.write_text("local version")
        r = self.client.post(
            "/upload",
            data={
                "path": "conflict.txt",
                "origin": "remote-node",
                "compressed": "false",
                "base_hash": "stale-hash-that-doesnt-match",
            },
            files={"file": ("conflict.txt", b"remote version")},
            headers=self.headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "conflict"
        assert "conflict_file" in body

    def test_delete_success(self):
        dest = Path(self.settings.sync_folder) / "bye.txt"
        dest.write_text("gone soon")
        r = self.client.delete(
            "/delete", params={"path": "bye.txt"}, headers=self.headers
        )
        assert r.status_code == 200
        assert not dest.exists()

    def test_delete_not_found(self):
        r = self.client.delete(
            "/delete", params={"path": "nope.txt"}, headers=self.headers
        )
        assert r.status_code == 404

    def test_path_traversal_blocked(self):
        r = self.client.post(
            "/upload",
            data={"path": "../../etc/passwd", "origin": "n", "compressed": "false"},
            files={"file": ("passwd", b"bad")},
            headers=self.headers,
        )
        assert r.status_code == 403

    def test_index_returns_files(self, db):
        db.upsert_file("indexed.txt", "abc", 1.0, 5)
        r = self.client.get("/index", headers=self.headers)
        assert r.status_code == 200
        data = r.json()
        assert any(f["path"] == "indexed.txt" for f in data)


# ── peer discovery ───────────────────────────────────────────────────────────


class TestPeerManager:
    @pytest.fixture(autouse=True)
    def setup(self, settings):
        from core.peer_manager import PeerManager

        self.settings = settings
        self.pm = PeerManager(settings)

    def test_register_rejects_self(self):
        ok, msg = self.pm.register("https://x:8000", self.settings.node_id, "127.0.0.1")
        assert not ok
        assert "self" in msg.lower()

    def test_rate_limiter_blocks(self):
        from core.peer_manager import RateLimiter

        rl = RateLimiter(window=60.0, limit=3)
        assert rl.allow("ip1") is True
        assert rl.allow("ip1") is True
        assert rl.allow("ip1") is True
        assert rl.allow("ip1") is False
        assert rl.allow("ip2") is True

    def test_max_peers_enforced(self, settings):
        from core.peer_manager import PeerManager

        settings.max_peers = 2
        pm = PeerManager(settings)
        from core.peer_manager import PeerRecord

        with pm._lock:
            pm._peers["https://a:8000"] = PeerRecord("https://a:8000", "a")
            pm._peers["https://b:8000"] = PeerRecord("https://b:8000", "b")
        ok, msg = pm.register("https://c:8000", "c", "127.0.0.1")
        assert not ok
        assert "limit" in msg.lower()

    def test_active_urls_excludes_dead_peers(self):
        from core.peer_manager import PeerRecord, MAX_CONSECUTIVE_FAILURES

        with self.pm._lock:
            alive = PeerRecord("https://alive:8000", "alive")
            dead = PeerRecord("https://dead:8000", "dead")
            dead.failures = MAX_CONSECUTIVE_FAILURES
            self.pm._peers["https://alive:8000"] = alive
            self.pm._peers["https://dead:8000"] = dead

        urls = self.pm.active_urls
        assert "https://alive:8000" in urls
        assert "https://dead:8000" not in urls

    def test_all_peers_returns_info(self):
        from core.peer_manager import PeerRecord

        with self.pm._lock:
            self.pm._peers.clear()
            self.pm._peers["https://p:8000"] = PeerRecord("https://p:8000", "p1")
        peers = self.pm.all_peers
        assert len(peers) == 1
        assert peers[0]["node_id"] == "p1"
        assert peers[0]["alive"] is True


class TestPeerEndpoints:
    @pytest.fixture(autouse=True)
    def setup_app(self, settings, db):
        from fastapi.testclient import TestClient
        from core.server import app
        from core.peer_manager import PeerManager

        app.state.settings = settings
        app.state.db = db
        pm = PeerManager(settings)
        app.state.peer_manager = pm
        self.pm = pm
        self.client = TestClient(app)
        self.headers = {"x-api-key": "test-key"}
        self.settings = settings

    def test_register_rejects_missing_fields(self):
        r = self.client.post("/peers/register", json={}, headers=self.headers)
        assert r.status_code == 422

    def test_register_rejects_bad_key(self):
        r = self.client.post(
            "/peers/register",
            json={"url": "https://x:8000", "node_id": "n"},
            headers={"x-api-key": "wrong"},
        )
        assert r.status_code == 403

    def test_register_rejects_self_registration(self):
        r = self.client.post(
            "/peers/register",
            json={"url": "https://x:8000", "node_id": self.settings.node_id},
            headers=self.headers,
        )
        assert r.status_code == 400

    def test_peers_list_requires_auth(self):
        r = self.client.get("/peers")
        assert r.status_code == 403

    def test_peers_list_returns_array(self):
        r = self.client.get("/peers", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── admin token auth ─────────────────────────────────────────────────────────


class TestAdminAuth:
    @pytest.fixture(autouse=True)
    def setup_app(self, settings, db):
        from fastapi.testclient import TestClient
        from core.server import app

        app.state.settings = settings
        app.state.db = db
        app.state.peer_manager = None
        app.state.orchestrator = None
        self.client = TestClient(app)
        self.admin_headers = {"Authorization": f"Bearer {settings.admin_token}"}
        self.bad_headers = {"Authorization": "Bearer wrong-token"}
        self.settings = settings

    def test_management_route_rejects_no_token(self):
        r = self.client.get("/api/v1/status")
        assert r.status_code == 401

    def test_management_route_rejects_bad_token(self):
        r = self.client.get("/api/v1/status", headers=self.bad_headers)
        assert r.status_code == 401

    def test_management_route_accepts_valid_token(self):
        r = self.client.get("/api/v1/status", headers=self.admin_headers)
        assert r.status_code == 200

    def test_sync_routes_still_use_api_key(self):
        r = self.client.get("/index", headers={"x-api-key": "test-key"})
        assert r.status_code == 200

    def test_sync_routes_reject_admin_token(self):
        r = self.client.get("/index", headers=self.admin_headers)
        assert r.status_code == 403


# ── management API ───────────────────────────────────────────────────────────


class TestManagementAPI:
    @pytest.fixture(autouse=True)
    def setup_app(self, settings, db):
        from fastapi.testclient import TestClient
        from core.server import app

        app.state.settings = settings
        app.state.db = db
        app.state.peer_manager = None
        app.state.orchestrator = None
        self.client = TestClient(app)
        self.admin = {"Authorization": f"Bearer {settings.admin_token}"}
        self.settings = settings
        self.db = db

    def test_get_status(self):
        r = self.client.get("/api/v1/status", headers=self.admin)
        assert r.status_code == 200
        data = r.json()
        assert "node_id" in data
        assert data["node_id"] == "test-node"
        assert "uptime" in data

    def test_get_config_redacts_secrets(self):
        r = self.client.get("/api/v1/config", headers=self.admin)
        assert r.status_code == 200
        data = r.json()
        assert data["api_key"] == "***"
        assert data["admin_token"] == "***"

    def test_get_files(self):
        self.db.upsert_file("test.py", "h1", 1.0, 10)
        r = self.client.get("/api/v1/files", headers=self.admin)
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_get_files_search(self):
        self.db.upsert_file("docs/readme.md", "h1", 1.0, 10)
        self.db.upsert_file("src/main.py", "h2", 2.0, 20)
        r = self.client.get("/api/v1/files?search=docs", headers=self.admin)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["path"] == "docs/readme.md"

    def test_get_conflicts_empty(self):
        r = self.client.get("/api/v1/conflicts", headers=self.admin)
        assert r.status_code == 200
        assert r.json() == []

    def test_conflict_crud(self):
        cid = self.db.record_conflict("a.txt", "a_conflict.txt", "peer-1")
        r = self.client.get("/api/v1/conflicts", headers=self.admin)
        assert len(r.json()) == 1
        r2 = self.client.post(f"/api/v1/conflicts/{cid}/resolve", headers=self.admin)
        assert r2.status_code == 200
        r3 = self.client.get("/api/v1/conflicts", headers=self.admin)
        assert len(r3.json()) == 0

    def test_get_queue(self):
        self.db.push_task("upload", "q.txt", "/q")
        r = self.client.get("/api/v1/queue", headers=self.admin)
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_clear_queue(self):
        self.db.push_task("upload", "q.txt", "/q")
        r = self.client.delete("/api/v1/queue", headers=self.admin)
        assert r.status_code == 200
        assert r.json()["count"] >= 1

    def test_queue_pause_resume(self):
        r = self.client.post("/api/v1/queue/pause", headers=self.admin)
        assert r.status_code == 200
        r2 = self.client.post("/api/v1/queue/resume", headers=self.admin)
        assert r2.status_code == 200

    def test_get_peers_empty(self):
        r = self.client.get("/api/v1/peers", headers=self.admin)
        assert r.status_code == 200
        assert r.json() == []

    def test_get_logs(self):
        r = self.client.get("/api/v1/logs", headers=self.admin)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_ignore(self):
        r = self.client.get("/api/v1/ignore", headers=self.admin)
        assert r.status_code == 200
        assert "content" in r.json()

    def test_add_and_remove_peer(self):
        from core.peer_manager import PeerManager
        from utils.trust_store import TrustStore
        from core.server import app

        pm = PeerManager(self.settings)
        app.state.peer_manager = pm
        ts = TrustStore(self.settings.trust_store_path)
        app.state.trust_store = ts
        # add_peer will fail verification since no real peer exists, but we test the route
        r = self.client.post(
            "/api/v1/peers", json={"url": "https://fake:9999"}, headers=self.admin
        )
        # Peer verification will fail so we expect 502 (Bad Gateway) because it can't fetch identity
        assert r.status_code == 502

    def test_put_ignore(self):
        r = self.client.put(
            "/api/v1/ignore", json={"content": "*.log\n*.tmp\n"}, headers=self.admin
        )
        assert r.status_code == 200
        assert r.json()["status"] == "updated"

    def test_retry_task(self):
        tid = self.db.push_task("upload", "rt.txt", "/rt")
        task = self.db.pop_task(time.time() + 1)
        self.db.fail_task(task["id"], time.time() + 9999)
        r = self.client.post(f"/api/v1/queue/{task['id']}/retry", headers=self.admin)
        assert r.status_code == 200


# ── WebSocket ────────────────────────────────────────────────────────────────


class TestWebSocket:
    @pytest.fixture(autouse=True)
    def setup_app(self, settings, db):
        from fastapi.testclient import TestClient
        from core.server import app

        app.state.settings = settings
        app.state.db = db
        self.client = TestClient(app)
        self.settings = settings

    def test_ws_connect_valid_token(self):
        with self.client.websocket_connect(
            f"/api/v1/ws?token={self.settings.admin_token}"
        ) as ws:
            assert ws is not None

    def test_ws_connect_no_token_rejected(self):
        try:
            with self.client.websocket_connect("/api/v1/ws") as ws:
                ws.receive_text()
            assert False, "Should have been rejected"
        except Exception:
            pass

    def test_ws_connect_bad_token_rejected(self):
        try:
            with self.client.websocket_connect("/api/v1/ws?token=wrong") as ws:
                ws.receive_text()
            assert False, "Should have been rejected"
        except Exception:
            pass


# ── queue worker pause/resume ────────────────────────────────────────────────


class TestQueueWorkerControls:
    def test_pause_resume(self, db, settings):
        from core.queue_worker import QueueWorker

        worker = QueueWorker(db, None, settings)
        assert worker.is_paused is False
        worker.pause()
        assert worker.is_paused is True
        worker.resume()
        assert worker.is_paused is False

    def test_clear_all(self, db, settings):
        from core.queue_worker import QueueWorker

        db.push_task("upload", "a.txt", "/a")
        db.push_task("delete", "b.txt")
        worker = QueueWorker(db, None, settings)
        count = worker.clear_all()
        assert count == 2
        assert db.pending_count() == 0

    def test_retry_task(self, db, settings):
        from core.queue_worker import QueueWorker

        db.push_task("upload", "r.txt", "/r")
        task = db.pop_task(time.time() + 1)
        db.fail_task(task["id"], time.time() + 9999)
        worker = QueueWorker(db, None, settings)
        assert worker.retry_task(task["id"]) is True
        t = db.pop_task(time.time() + 1)
        assert t is not None


# ── setup detection ──────────────────────────────────────────────────────────


class TestSetupDetection:
    def test_setup_not_complete_default(self, tmp_path):
        s = Settings(
            sync_folder=str(tmp_path / "s"),
            db_path=str(tmp_path / "t.db"),
            setup_complete=False,
        )
        assert s.setup_complete is False

    def test_setup_complete_when_set(self, tmp_path):
        s = Settings(
            sync_folder=str(tmp_path / "s"),
            db_path=str(tmp_path / "t.db"),
            setup_complete=True,
        )
        assert s.setup_complete is True


# ── config write_env ─────────────────────────────────────────────────────────


class TestWriteEnv:
    def test_write_env_creates_file(self, tmp_path):
        env_path = str(tmp_path / ".env")
        write_env({"API_KEY": "new-key", "PORT": "9000"}, env_path=env_path)
        content = Path(env_path).read_text()
        assert "API_KEY=new-key" in content
        assert "PORT=9000" in content

    def test_write_env_updates_existing(self, tmp_path):
        env_path = str(tmp_path / ".env")
        Path(env_path).write_text("API_KEY=old\nPORT=8000\n")
        write_env({"API_KEY": "new"}, env_path=env_path)
        content = Path(env_path).read_text()
        assert "API_KEY=new" in content
        assert "PORT=8000" in content
        assert "old" not in content


# ── setup endpoint ───────────────────────────────────────────────────────────


class TestSetupEndpoint:
    @pytest.fixture(autouse=True)
    def setup_app(self, settings, db):
        from fastapi.testclient import TestClient
        from core.server import app

        app.state.settings = settings
        app.state.db = db
        app.state.peer_manager = None
        app.state.orchestrator = None
        self.client = TestClient(app)
        self.settings = settings

    def test_setup_endpoint(self):
        r = self.client.post(
            "/api/v1/setup",
            json={
                "sync_folder": self.settings.sync_folder,
                "api_key": "new-secure-key",
                "node_id": "my-node",
                "peers": "",
            },
            headers={"Authorization": f"Bearer {self.settings.admin_token}"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "admin_token" in data


# ── SSL certificate generation ───────────────────────────────────────────────


class TestCerts:
    def test_generate_self_signed_cert(self, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        generate_self_signed_cert(cert, key)
        assert cert.is_file()
        assert key.is_file()
        assert b"BEGIN CERTIFICATE" in cert.read_bytes()
        assert b"BEGIN RSA PRIVATE KEY" in key.read_bytes()

    def test_ensure_certs_creates_if_missing(self, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        created = ensure_certs(cert, key)
        assert created is True
        assert cert.is_file()

    def test_ensure_certs_skips_if_exist(self, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("existing")
        key.write_text("existing")
        created = ensure_certs(cert, key)
        assert created is False
        assert cert.read_text() == "existing"


# ── bootstrap_env ────────────────────────────────────────────────────────────


class TestBootstrapEnv:
    def test_bootstrap_creates_env(self, tmp_path, monkeypatch):
        import config

        monkeypatch.setattr(config, "_BASE_DIR", tmp_path)
        env_path = tmp_path / ".env"
        assert not env_path.exists()
        result = config.bootstrap_env()
        assert result is True
        assert env_path.is_file()
        content = env_path.read_text()
        assert "API_KEY=" in content
        assert "ADMIN_TOKEN=" in content
        assert "change-me" not in content

    def test_bootstrap_skips_if_exists(self, tmp_path, monkeypatch):
        import config

        monkeypatch.setattr(config, "_BASE_DIR", tmp_path)
        env_path = tmp_path / ".env"
        env_path.write_text("API_KEY=existing\n")
        result = config.bootstrap_env()
        assert result is False
        assert "existing" in env_path.read_text()
