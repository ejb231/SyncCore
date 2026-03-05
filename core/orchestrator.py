"""Component lifecycle manager - starts, stops, and reconfigures all services."""

from __future__ import annotations

import threading

from utils.logging import get_logger
from utils.resilience import SupervisedThread

log = get_logger("orchestrator")


class Orchestrator:
    """Owns references to every SyncCore component and coordinates their lifecycle.

    Background threads for the watcher, queue worker, and peer manager are
    wrapped in :class:`SupervisedThread` so they auto-restart on unexpected
    crashes (up to *max_restarts* times).
    """

    def __init__(
        self, settings, db, ignore, peer_manager, watcher, queue_worker, client
    ) -> None:
        self.settings = settings
        self.db = db
        self.ignore = ignore
        self.peer_manager = peer_manager
        self.watcher = watcher
        self.queue_worker = queue_worker
        self.client = client
        self._lock = threading.Lock()
        self._supervised: list[SupervisedThread] = []

    # ------------------------------------------------------------------
    # Supervised wrappers
    # ------------------------------------------------------------------

    def _supervise(self, name: str, target, *args, **kwargs) -> SupervisedThread:
        """Wrap *target* in a SupervisedThread and start it."""
        st = SupervisedThread(
            target=target,
            name=name,
            max_restarts=5,
            restart_delay=2.0,
            args=args,
            kwargs=kwargs,
        )
        st.start()
        self._supervised.append(st)
        return st

    def start_all(self) -> None:
        with self._lock:
            if self.peer_manager:
                self.peer_manager.start()
            if self.queue_worker:
                self.queue_worker.start()
            if self.watcher:
                self.watcher.start()
            log.info("All components started")

    def stop_all(self) -> None:
        with self._lock:
            for name in ("watcher", "queue_worker", "peer_manager"):
                comp = getattr(self, name, None)
                if comp and hasattr(comp, "stop"):
                    try:
                        comp.stop()
                    except Exception as exc:
                        log.warning("Error stopping %s: %s", name, exc)
            # Stop all supervised threads
            for st in self._supervised:
                st.stop()
            self._supervised.clear()
            log.info("All components stopped")

    def restart_component(self, name: str) -> None:
        with self._lock:
            comp = getattr(self, name, None)
            if comp is None:
                raise ValueError(f"Unknown component: {name}")
            if hasattr(comp, "stop"):
                comp.stop()
            if hasattr(comp, "start"):
                comp.start()
            log.info("Restarted component: %s", name)

    def reconfigure(self, new_settings) -> None:
        """Stop all components, apply new settings, then restart."""
        with self._lock:
            for comp_name in ("watcher", "queue_worker", "peer_manager"):
                comp = getattr(self, comp_name, None)
                if comp and hasattr(comp, "stop"):
                    comp.stop()

            self.settings = new_settings
            for comp in (
                self.peer_manager,
                self.queue_worker,
                self.watcher,
                self.client,
            ):
                if comp:
                    comp.settings = new_settings

            for comp_name in ("peer_manager", "queue_worker", "watcher"):
                comp = getattr(self, comp_name, None)
                if comp and hasattr(comp, "start"):
                    comp.start()

            log.info("Reconfigured and restarted all components")
