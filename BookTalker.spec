# -*- mode: python ; coding: utf-8 -*-
# Build with build.bat (runs: pyinstaller BookTalker.spec)
# Bundled: what every user needs. Extra voices and both translators (fast 600 MB, AI 2.6 GB) download on
# request (bt/packs.py); the fast translator's zip is an asset of the GitHub release 'models-1'.
import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [('models/layout.onnx', 'models'), ('models/layout.json', 'models'),   # 8-bit layout model
         ('models/ocr', 'models/ocr'),                    # OCR (Chinese/English/Japanese + Latin, Cyrillic, Korean, Greek, Arabic, Hindi, Thai, Tamil, Telugu)
         ('models/tessdata', 'models/tessdata'),          # Tesseract readers: Bengali, Punjabi, Gujarati, Malayalam, Kannada, Sinhala, Burmese, Khmer, Lao, Tibetan, Georgian, Armenian, Amharic, Hebrew, Yiddish
         ('booktalker.ico', '.'),
         ('LICENSE', '.'), ('THIRD_PARTY_NOTICES.md', '.'), ('licenses', 'licenses'),   # shown under About > Credits & licences
         ('art/hero.png', 'art'), ('art/about.png', 'art'), ('art/logo_256.png', 'art')]
DEFAULT_VOICE = 'en_GB-alba-medium'     # recordings CC BY 4.0: free to share (Lessac's are research-only)
datas += [(f, 'voices') for f in glob.glob(f'voices/{DEFAULT_VOICE}.ort') + glob.glob(f'voices/{DEFAULT_VOICE}.onnx.json')]
datas += collect_data_files('piper')           # espeak-ng data
datas += collect_data_files('fast_langdetect')   # lid.176.ftz language-ID model
datas += collect_data_files('rapidocr', excludes=['**/*.onnx'])   # configs; models live in models/ocr
datas += collect_data_files('certifi')         # HTTPS for downloads
datas += collect_data_files('unicode_rbnf')    # numbers spoken in Chinese and Thai
datas += [('bt/piperx/lithuanian', 'bt/piperx/lithuanian')]   # Lithuanian stress dictionary
# word lists: full lists for languages with voices (rare words matter for the broken-text check),
# small lists for the rest; no Chinese segmenter dictionary (not used)
KEEP_LARGE = {'en', 'fr', 'de', 'es', 'it', 'pt', 'ru', 'nl'}
for src, dest in collect_data_files('wordfreq'):
    name = os.path.basename(src)
    if name.startswith('jieba') or (name.startswith('large_') and name[6:8] not in KEEP_LARGE):
        continue
    datas.append((src, dest))
binaries = collect_dynamic_libs('onnxruntime') + collect_dynamic_libs('ctranslate2') + collect_dynamic_libs('tesserocr')

a = Analysis(
    ['booktalker.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=['bt.voiceproc', 'bt.export', 'lameenc'] + collect_submodules('tesserocr')   # incl. its cysignals helper; MP3 encoder
                  # voices that pronounce through bt/piperx: Chinese 'pinyin', Lithuanian, Thai (TLTK's
                  # nlp.py loads from the packs folder and needs these standard modules)
                  + ['bt.piperx', 'bt.piperx.phonemize_lithuanian', 'bt.piperx.bert_tokenizer',
                     'piper.phonemize_chinese', 'piper.g2pw_onnx', 'piper.phonemize_thai',
                     'unicode_rbnf', 'sentence_stream', 'pydoc', 'statistics', 'bz2', 'pickle'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # the layout model runs on onnxruntime: none of the torch stack is needed.
    # (onnx stays: downloaded voices get their word-timing output added at load.)
    excludes=['torch', 'torchvision', 'transformers', 'surya', 'marker', 'matplotlib',
              'tkinter', 'IPython', 'scipy', 'sklearn', 'sympy', 'pandas', 'rapid_layout',
              'cryptography', 'google'],     # (pulled in by a Google tool in the build folder, never by BookTalker)
    noarchive=False,
    optimize=0,
)
# never loaded by BookTalker (audit 10-08, ~90 MB): OpenCV's video codec, Qt's software OpenGL and its
# QML/Quick/virtual-keyboard/PDF/network modules with the plugins that need them
UNUSED = ('opencv_videoio_ffmpeg', 'opengl32sw', 'qt6quick', 'qt6qml', 'qt6virtualkeyboard', 'qt6pdf',
          'qt6network', 'qt6opengl', 'qtnetwork', 'qtvirtualkeyboardplugin', 'qpdf', 'qnetworklistmanager',
          'qschannelbackend', 'qcertonlybackend', 'qopensslbackend')
a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).lower().startswith(UNUSED)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BookTalker',
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
    icon=['booktalker.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BookTalker',
)
