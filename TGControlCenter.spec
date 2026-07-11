# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH)
SCRIPTS = ROOT / "scripts"

hiddenimports = [
    "bot",
    "admin_dashboard",
    "bot_api_client",
    "categories",
    "categorize",
    "export_frontend_data",
    "filter_rules",
    "listener_settings",
    "manage_ads",
    "message_indexer",
    "search_entries",
]

datas = [
    (str(ROOT / "data" / "rectg.db"), "data"),
    (str(ROOT / ".env.example"), "."),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "web" / "dist"), "web/dist"),
]

a = Analysis(
    [str(ROOT / "control_center.py")],
    pathex=[str(ROOT), str(SCRIPTS)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TG索引控制中心",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TG索引控制中心",
)
