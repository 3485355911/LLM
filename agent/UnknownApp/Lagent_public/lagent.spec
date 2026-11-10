# -*- mode: python ; coding: utf-8 -*-
# 源码位置：Lagent/
# 产物位置：d:\LLm\agent\UnknownApp\（根目录，含 UnknownApp.exe + _internal/）

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('tui/app.tcss', 'tui'),
    ],
    hiddenimports=[
        # Textual 运行时动态导入的组件
        'tui.app',
        'tui.commands',
        'tui.theme',
        'tui.widgets.chat',
        'tui.widgets.composer',
        'tui.widgets.sidebar',
        'tui.widgets.status',
        'tui.widgets.topbar',
        'tui',
        # core 子模块
        'core.agent',
        'core.config',
        'core.context',
        'core.events',
        'core.mcp',
        'core.messages',
        'core.session',
        'core.skills',
        'core.llm.client',
        'core.llm.protocol',
        'core.tools.base',
        'core.tools.context',
        'core.tools.fetchweb',
        'core.tools.filesystem',
        'core.tools.runcli',
        'core.tools.search',
        'core.tools.skills',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # GUI 框架：完全不用，排除减小体积
        'PyQt5', 'PySide6', 'PyQt6', 'PySide2', 'qtpy',
        'tkinter', 'tcl', 'tk', 'Tkinter',
        # 重量级科学/数据库
        'pandas', 'numpy', 'matplotlib', 'scipy',
        'sympy', 'numba', 'cupyx',
        # Office 文档（用 officecli 命令行工具，不走 Python 库）
        'openpyxl', 'lxml', 'docx', 'pptx', 'pdfminer',
        # Web / ORM / 其它无关
        'sqlalchemy', 'django', 'flask', 'fastapi',
        'zmq', 'tornado', 'aiohttp', 'websockets',
        'jupyter', 'notebook', 'ipython',
        'setuptools', 'pip', 'wheel', 'pkg_resources',
        'unittest', 'pytest', 'doctest', 'test',
    ],
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
    name='UnknownApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
