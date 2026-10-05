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
    a.binaries,
    a.datas,
    [],
    name="topstep-local-executor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
