# -*- mode: python ; coding: utf-8 -*-

runtime_datas = [
    ('config', 'workspace/config'),
    ('content', 'workspace/content'),
    ('sites', 'workspace/sites'),
    ('docs', 'workspace/docs'),
    ('ops', 'workspace/ops'),
    ('reports', 'workspace/reports'),
]

hiddenimports = [
    'src',
    'src.growth_os',
    'src.growth_os.audit',
    'src.growth_os.config',
    'src.growth_os.content_store',
    'src.growth_os.desktop_app',
    'src.growth_os.dnsgen',
    'src.growth_os.image_enrichment',
    'src.growth_os.news_automation',
    'src.growth_os.autonomous_daemon',
    'src.growth_os.runtime_network',
    'src.growth_os.server',
    'src.growth_os.sitegen',
    'tkinter',
]

a = Analysis(
    ['launch_desktop.py'],
    pathex=[],
    binaries=[],
    datas=runtime_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TurkiyeGundemiApp-debug-console',
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
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TurkiyeGundemiApp',
)
