# -*- mode: python ; coding: utf-8 -*-
# Build with (on Windows):  pyinstaller vault_windows.spec
# Produces: dist/Vault Authenticator/Vault Authenticator.exe

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=['app', 'storage', 'migration_parser'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Vault Authenticator',
    debug=False,
    strip=False,
    upx=True,
    console=False,           # no console window
    icon='icon/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='Vault Authenticator',
)
