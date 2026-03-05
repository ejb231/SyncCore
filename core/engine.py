"""Initial scan of the sync folder — diffs against the DB and queues work."""

from __future__ import annotations

from pathlib import Path

from utils.file_ops import calculate_hash
from utils.logging import get_logger

log = get_logger("engine")


class SyncEngine:
    """Performs a one-time scan on startup, detecting new/modified/deleted files."""

    def __init__(self, settings, db, ignore) -> None:
        self.settings = settings
        self.db = db
        self.ignore = ignore

    def initial_scan(self) -> int:
        """Walk sync_folder, compare against the DB, and queue changes.

        Returns the number of tasks queued.
        """
        sync_root = Path(self.settings.sync_folder)
        queued = 0

        known_paths: set[str] = {row["path"] for row in self.db.all_files()}
        seen: set[str] = set()

        for file in sync_root.rglob("*"):
            if not file.is_file():
                continue
            rel = file.relative_to(sync_root).as_posix()
            if self.ignore.is_ignored(rel):
                continue
            seen.add(rel)

            stat = file.stat()
            db_row = self.db.get_file(rel)

            if not db_row:
                file_hash = calculate_hash(file)
                self.db.upsert_file(
                    rel,
                    file_hash,
                    stat.st_mtime,
                    stat.st_size,
                    origin=self.settings.node_id,
                )
                self.db.push_task("upload", rel, str(file))
                queued += 1
                log.info("New file queued: %s", rel)
            elif stat.st_mtime != db_row["mtime"] or stat.st_size != db_row["size"]:
                file_hash = calculate_hash(file)
                if file_hash != db_row["hash"]:
                    self.db.upsert_file(
                        rel,
                        file_hash,
                        stat.st_mtime,
                        stat.st_size,
                        origin=self.settings.node_id,
                        version=db_row["version"] + 1,
                    )
                    self.db.push_task("upload", rel, str(file))
                    queued += 1
                    log.info("Changed file queued: %s", rel)

        for rel in known_paths - seen:
            self.db.delete_file(rel)
            self.db.push_task("delete", rel)
            queued += 1
            log.info("Deleted file queued: %s", rel)

        log.info("Initial scan complete - %d tasks queued", queued)
        return queued

    def pull_from_peers(self, client) -> int:
        """Fetch the file index from each peer and download files we're missing.

        This handles files that appeared on peers while this node was offline.
        Returns the total number of files downloaded.
        """
        downloaded = 0
        sync_root = Path(self.settings.sync_folder)

        for target in client.targets:
            try:
                remote_files = client.fetch_index(target)
            except Exception as exc:
                log.warning("Could not fetch index from %s: %s", target, exc)
                continue

            for entry in remote_files:
                rel = entry.get("path", "")
                remote_hash = entry.get("hash", "")
                if not rel or not remote_hash:
                    continue
                if self.ignore.is_ignored(rel):
                    continue

                local_row = self.db.get_file(rel)
                local_file = sync_root / rel

                # Skip if we already have this exact version
                if local_row and local_row["hash"] == remote_hash:
                    continue

                # Skip if local file exists but wasn't in our DB (just scanned)
                if local_file.is_file() and not local_row:
                    local_hash = calculate_hash(local_file)
                    if local_hash == remote_hash:
                        continue

                # We're missing this file or have an older version — queue a
                # download by recording the need.  The actual download is done
                # by the upload endpoint on the remote peer when we request it.
                # For now, we fetch the file directly via the client.
                try:
                    self._download_file(client, target, rel, remote_hash, sync_root)
                    downloaded += 1
                except Exception as exc:
                    log.warning("Failed to pull %s from %s: %s", rel, target, exc)

        if downloaded:
            log.info("Pulled %d file(s) from peers", downloaded)
        return downloaded

    def _download_file(
        self, client, target: str, rel_path: str, expected_hash: str, sync_root: Path
    ) -> None:
        """Download a single file from a peer's /download endpoint."""
        data = client.download_file_bytes(target, rel_path)
        if data is None:
            log.debug(
                "Peer %s has no /download endpoint, skipping pull for %s",
                target,
                rel_path,
            )
            return

        from utils.file_ops import hash_bytes

        actual_hash = hash_bytes(data)
        if actual_hash != expected_hash:
            log.warning(
                "Hash mismatch pulling %s from %s (expected %s, got %s)",
                rel_path,
                target,
                expected_hash[:12],
                actual_hash[:12],
            )
            return

        dest = sync_root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Mark write guard to prevent watcher from re-syncing
        from core.server import mark_server_write

        mark_server_write(rel_path)

        tmp = dest.with_suffix(dest.suffix + ".synctmp")
        try:
            tmp.write_bytes(data)
            import os

            os.replace(str(tmp), str(dest))
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

        stat = dest.stat()
        self.db.upsert_file(
            rel_path,
            actual_hash,
            stat.st_mtime,
            stat.st_size,
            origin="remote",
        )
        log.info("Pulled: %s from %s", rel_path, target)
