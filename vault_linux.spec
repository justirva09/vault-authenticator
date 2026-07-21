# -*- mode: python ; coding: utf-8 -*-
# Build with (on Linux):  pyinstaller vault_linux.spec
# Produces: dist/vault-authenticator/vault-authenticator
#
# Note: PyInstaller can't embed an icon into a Linux binary the way it can
# for macOS/Windows. Icon + menu integration on Linux is done via a
# .desktop file instead - see install_linux.sh.

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
    name='vault-authenticator',
    debug=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='vault-authenticator',
)
