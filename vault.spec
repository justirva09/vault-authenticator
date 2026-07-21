# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller vault.spec
# Produces: dist/Vault Authenticator.app

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
    console=False,      # no terminal window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='Vault Authenticator',
)

app = BUNDLE(
    coll,
    name='Vault Authenticator.app',
    icon='icon/AppIcon.icns',
    bundle_identifier='local.vault.authenticator',
    info_plist={
        'NSCameraUsageDescription': 'Vault uses your camera to scan the QR code shown by Google Authenticator when importing accounts.',
        'NSHighResolutionCapable': True,
        'LSUIElement': False,
    },
)
