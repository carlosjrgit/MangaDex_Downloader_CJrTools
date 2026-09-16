# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['mangadex_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('index.pb', '.')
    ],
    hiddenimports=[
        'providers',
        'manga_core',
        'mangalivre',
        'about_dialog',
        'icons',
        'styles',
        'keiyoushi_catalog',
        'source_catalog_fetcher',
        'chapter_download_dialog',
        'keiyoushi_dialog',
        'playwright',
        'playwright.sync_api',
        'bs4',
        'tqdm',
        'urllib3',
        'requests'
    ],
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
    a.binaries,
    a.datas,
    [],
    name='MangaHubRip_CJrTools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
