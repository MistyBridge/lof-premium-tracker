# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置
将 LOF 基金后端服务打包为 Windows 可执行文件

使用方法：在项目根目录执行
  py -m PyInstaller installer/lof_service.spec --noconfirm --clean
"""

block_cipher = None

a = Analysis(
    ['../app.py'],
    pathex=['..'],
    binaries=[],
    datas=[
        ('../sz_lof_codes.json', '.'),
    ],
    hiddenimports=[
        'flask',
        'flask.cors',
        'flask_cors',
        'apscheduler',
        'apscheduler.schedulers.background',
        'apscheduler.triggers.interval',
        'requests',
        'logging',
        'json',
        'datetime',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'matplotlib', 'PIL', 'Pillow',
        'numpy', 'scipy', 'pandas',
        'tkinter',
        'IPython', 'jupyter',
        'pytest', 'sphinx',
        'zmq',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LOF基金服务',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
