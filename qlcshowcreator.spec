# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for QLC+ Show Creator (bundled with Visualizer)."""

import os

project_root = os.path.abspath(SPECPATH)

a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=[],
    datas=[
        ('custom_fixtures', 'custom_fixtures'),
        ('resources', 'resources'),
        ('riffs', 'riffs'),
        ('visualizer', 'visualizer'),
        # Starter rigs + demo shows for File -> New from Template. Only
        # rigs/ and shows/ — demos/media, demos/reference and the
        # generator scripts stay out of the bundle.
        ('demos/rigs', 'demos/rigs'),
        ('demos/shows', 'demos/shows'),
    ],
    hiddenimports=[
        'visualizer',
        'visualizer.main',
        'visualizer.artnet',
        'visualizer.artnet.listener',
        'visualizer.renderer',
        'visualizer.renderer.camera',
        'visualizer.renderer.engine',
        'visualizer.renderer.fixtures',
        'visualizer.renderer.gizmo',
        'visualizer.renderer.stage',
        'visualizer.tcp',
        'visualizer.tcp.client',
        # config is a namespace package (no __init__.py)
        'config.models',
        'config.compact_serializer',
        # gui subpackages
        'gui.dialogs',
        'gui.dialogs.autogen_dialog',
        'gui.dialogs.generation_inspector',
        'gui.dialogs.orientation_dialog',
        'gui.dialogs.render_dialog',
        'gui.dialogs.workspace_options_dialog',
        'gui.tabs',
        'gui.tabs.base_tab',
        'gui.tabs.configuration_tab',
        'gui.tabs.fixtures_tab',
        'gui.tabs.shows_tab',
        'gui.tabs.shows_tab_timeline',
        'gui.tabs.stage_tab',
        'gui.tabs.structure_tab',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Test deps the runtime doesn't need. requirements.txt installs pytest
    # for the CI test step; PyInstaller picks it up via static analysis
    # otherwise. Excluding keeps the bundle ~5-10 MB smaller.
    excludes=['pytest', '_pytest', 'hypothesis'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='QLCShowCreator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=os.path.join(project_root, 'resources', 'lightbulb.png'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='QLCShowCreator',
)
