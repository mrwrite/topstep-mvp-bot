# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "scripts" / "local_executor_entrypoint.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "local_executor" / "alembic.ini"), "local_executor"),
        (str(root / "local_executor" / "migrations"), "local_executor/migrations"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["app", "tests", "uvicorn", "fastapi", "celery", "gunicorn"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="topstep-local-executor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="topstep-local-executor",
)
app = BUNDLE(
    collection,
    name="Topstep Local Executor.app",
    icon=None,
    bundle_identifier="com.topstep-mvp-bot.local-executor",
    info_plist={
        "CFBundleDisplayName": "Topstep Local Executor",
        "CFBundleName": "Topstep Local Executor",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
)
