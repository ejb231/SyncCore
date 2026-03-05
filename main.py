"""SyncCore CLI - run, status, and reset commands."""

from __future__ import annotations

import signal
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import Settings, __version__, bootstrap_env, get_app_dir
from utils.certs import ensure_certs
from utils.logging import get_logger, setup_logging


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"SyncCore {__version__}")
        raise typer.Exit()


cli = typer.Typer(
    help="SyncCore - bidirectional file synchronisation",
    no_args_is_help=False,
    pretty_exceptions_enable=True,
)
console = Console()


@cli.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """SyncCore - bidirectional file synchronisation."""


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _boot(quiet: bool = False) -> tuple[Settings, "Database", "SyncIgnore", bool]:
    """Bootstrap the environment: load settings, create DB, parse ignore rules."""
    from utils.file_index import Database
    from utils.filters import SyncIgnore

    first_run = bootstrap_env()
    settings = Settings()
    settings.ensure_folders()

    if not quiet:
        setup_logging(settings.log_level, str(Path(settings.db_path).parent))

    generated_certs = ensure_certs(settings.ssl_cert, settings.ssl_key)

    db = Database(settings.db_path)
    ignore = SyncIgnore(settings.syncignore_path)
    return settings, db, ignore, first_run or generated_certs


def _print_banner(settings: Settings, first_run: bool) -> None:
    url = f"https://localhost:{settings.port}"
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan", min_width=14)
    table.add_column()
    table.add_row("URL", url)
    table.add_row("Node ID", settings.node_id)
    table.add_row("Sync folder", settings.sync_folder)
    table.add_row("Mode", "P2P bidirectional")
    if first_run:
        table.add_row("Admin token", settings.admin_token)
    else:
        table.add_row("Admin token", settings.admin_token[:8] + "...")
    if settings.peer_list:
        table.add_row("Peers", ", ".join(settings.peer_list))
    else:
        table.add_row("Peers", "[dim]none - add via web UI[/dim]")

    title = "[bold green]SyncCore is running[/bold green]"
    if first_run:
        title += "  [yellow](first run - config auto-generated)[/yellow]"

    console.print()
    console.print(Panel(table, title=title, border_style="green", expand=False))
    console.print()
    console.print(
        f"  [dim]Open[/dim] [bold underline blue]{url}[/bold underline blue] "
        "[dim]in your browser to manage SyncCore.[/dim]"
    )
    console.print("  [dim]Press[/dim] [bold]Ctrl+C[/bold] [dim]to stop.[/dim]")
    console.print()


@cli.command()
def run(
    server_only: bool = typer.Option(
        False, "--server", help="Run only the HTTPS server"
    ),
    client_only: bool = typer.Option(
        False, "--client", help="Run only the watcher + queue worker"
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Don't auto-open the browser on first run"
    ),
) -> None:
    """Start SyncCore (default: both server and client)."""
    from core.client import SyncClient
    from core.engine import SyncEngine
    from core.orchestrator import Orchestrator
    from core.peer_manager import PeerManager
    from core.queue_worker import QueueWorker
    from core.server import app as fastapi_app
    from core.watcher import FileWatcher

    settings, db, ignore, first_run = _boot()
    log = get_logger("main")

    if not settings.verify_tls:
        log.warning(
            "TLS certificate verification is DISABLED (verify_tls=false). "
            "Peer connections are encrypted but not authenticated. "
            "Set VERIFY_TLS=true in .env for production use."
        )

    if not client_only and not _port_available(settings.port):
        console.print(
            f"\n  [bold red]Error:[/bold red] Port {settings.port} is already in use.\n"
            f"  Change PORT in your .env or stop the other process.\n"
        )
        raise SystemExit(1)

    components: list = []
    stop_event = threading.Event()

    peer_mgr = PeerManager(settings)
    peer_mgr.start()
    components.append(peer_mgr)

    watcher = None
    worker = None
    client = None

    if not client_only:
        fastapi_app.state.settings = settings
        fastapi_app.state.db = db
        fastapi_app.state.peer_manager = peer_mgr

        ssl_key = settings.ssl_key if Path(settings.ssl_key).is_file() else None
        ssl_cert = settings.ssl_cert if Path(settings.ssl_cert).is_file() else None

        def _serve():
            uvicorn.run(
                fastapi_app,
                host="0.0.0.0",
                port=settings.port,
                ssl_keyfile=ssl_key,
                ssl_certfile=ssl_cert,
                log_level="warning",
            )

        srv_thread = threading.Thread(target=_serve, daemon=True, name="uvicorn")
        srv_thread.start()
        components.append(srv_thread)
        time.sleep(1)

    if not server_only:
        client = SyncClient(settings, peer_manager=peer_mgr)
        engine = SyncEngine(settings, db, ignore)
        engine.initial_scan()

        # Pull files we missed while offline
        try:
            engine.pull_from_peers(client)
        except Exception as exc:
            log.warning("Peer reconciliation failed: %s", exc)

        worker = QueueWorker(db, client, settings)
        worker.start()

        watcher = FileWatcher(settings, db, ignore)
        watcher.start()
        components.extend([worker, watcher])
        peer_mgr.announce_to_peers()

    orchestrator = Orchestrator(
        settings=settings,
        db=db,
        ignore=ignore,
        peer_manager=peer_mgr,
        watcher=watcher,
        queue_worker=worker,
        client=client,
    )
    fastapi_app.state.orchestrator = orchestrator

    _print_banner(settings, first_run)

    if first_run and not no_browser and not client_only:
        try:
            webbrowser.open(f"https://localhost:{settings.port}")
        except Exception:
            pass

    def _shutdown(*_):
        console.print("\n  [yellow]Shutting down...[/yellow]")
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    try:
        stop_event.wait()
    finally:
        orchestrator.stop_all()
        for c in components:
            if hasattr(c, "stop"):
                try:
                    c.stop()
                except Exception:
                    pass
        if db:
            db.close()


@cli.command()
def status():
    """Show node status and queue depth."""
    settings, db, _, _ = _boot(quiet=True)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan", min_width=14)
    table.add_column()
    table.add_row("Node ID", settings.node_id)
    table.add_row("Sync folder", settings.sync_folder)
    table.add_row("Port", str(settings.port))
    table.add_row(
        "Peers", ", ".join(settings.peer_list) if settings.peer_list else "(none)"
    )
    table.add_row("Indexed files", str(len(db.all_files())))
    table.add_row("Pending tasks", str(db.pending_count()))
    table.add_row(
        "Setup done",
        "[green]Yes[/green]" if settings.setup_complete else "[yellow]No[/yellow]",
    )

    console.print()
    console.print(
        Panel(
            table,
            title="[bold]SyncCore Status[/bold]",
            border_style="blue",
            expand=False,
        )
    )
    console.print()


@cli.command()
def reset():
    """Delete the .env and generated certs to start fresh."""
    base = get_app_dir()
    removed = []
    for name in (".env", "cert.pem", "key.pem"):
        p = base / name
        if p.is_file():
            p.unlink()
            removed.append(name)
    if removed:
        console.print(f"  [green]Removed:[/green] {', '.join(removed)}")
        console.print("  Run [bold]python main.py run[/bold] to set up again.")
    else:
        console.print("  [dim]Nothing to remove - already clean.[/dim]")


if __name__ == "__main__":
    # Default to 'run' when launched without arguments (e.g. double-click).
    if len(sys.argv) == 1:
        sys.argv.insert(1, "run")
    cli()
