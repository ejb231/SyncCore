# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SyncCore — one-folder distribution."""

import os

block_cipher = None
ROOT = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), ""))

# Ensure ROOT points to the SyncCore directory
if not os.path.isfile(os.path.join(ROOT, "main.py")):
    ROOT = os.path.abspath(".")

# Locate rich._unicode_data — files with dashes are loaded via importlib
import importlib, pathlib
_rich_ud_dir = pathlib.Path(importlib.import_module("rich._unicode_data").__file__).parent
_rich_ud_files = [
    (str(f), "rich/_unicode_data")
    for f in _rich_ud_dir.glob("*.py")
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Built React frontend
        (os.path.join(ROOT, "web", "dist"), os.path.join("web", "dist")),
        # Default ignore patterns shipped with the app
        (os.path.join(ROOT, ".syncignore"), "."),
        # Rich unicode data (filenames contain dashes, loaded dynamically)
    ] + _rich_ud_files,
    hiddenimports=[
        # FastAPI / Starlette internals that PyInstaller misses
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "uvicorn.lifespan",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.logging",
        "multipart",
        "multipart.multipart",
        # Pydantic
        "pydantic",
        "pydantic_settings",
        # Rich unicode data (dynamically imported modules with dashes in names)
        "rich._unicode_data",
        # Application packages
        "config",
        "core",
        "core.server",
        "core.client",
        "core.engine",
        "core.watcher",
        "core.queue_worker",
        "core.peer_manager",
        "core.management_api",
        "core.orchestrator",
        "core.ws",
        "utils",
        "utils.auth",
        "utils.certs",
        "utils.conflict",
        "utils.file_index",
        "utils.file_ops",
        "utils.filters",
        "utils.logging",
        "utils.paths",
        "utils.resilience",
        "utils.discovery",
        "utils.trust_store",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude dev/test dependencies to keep the bundle lean
        "pytest",
        "pytest_asyncio",
        "test",
        "tests",
        "tkinter",
        "_tkinter",
        "unittest",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SyncCore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SyncCore",
)
