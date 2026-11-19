"""Optional downloads ("packs"): extra voices and the AI translator are fetched from their
official public sources only when the user asks for them, keeping the app itself small.

    voices          huggingface.co/rhasspy/piper-voices          ~60 MB each
    AI translator   huggingface.co/bartowski (Qwen3-4B, Apache-2.0)  2.5 GB   (a computer with a graphics card)
                    huggingface.co/mradermacher (EuroMoE, Apache-2.0) 1.6 GB  (a computer without one)
                    github.com/ggml-org/llama.cpp (engine)         ~50 MB
"""
import io
import os
import ssl
import threading
import urllib.request
import zipfile

from .paths import package_family, resource

LLAMA_TAG = "b12521"
AI_MODEL_FILE = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
AI_MODEL_URL = f"https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/main/{AI_MODEL_FILE}"
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-{kind}-x64.zip"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{loc}/{name}/{quality}/{stem}.onnx"
AI_SIZE_MB = 2600
# A computer without a graphics card runs EuroMoE instead (the EuroLLM project, utter-project; Apache-2.0):
# 2.6B parameters of which 0.6B work on each word, so it keeps up on the processor. MEASURED on 4 processor
# threads, a Latvian book against Google's English of three chapters: chrF 64.4 at 1.4 s a sentence (the
# fast translator: 58.8 at 1.3 s; Qwen3-4B on the processor: 12 tokens/s, too slow to read along).
CPU_AI_FILE = "EuroMoE-2.6B-A0.6B-Instruct-2512.Q4_K_M.gguf"
CPU_AI_URL = ("https://huggingface.co/mradermacher/EuroMoE-2.6B-A0.6B-Instruct-2512-GGUF/resolve/"
              f"11be4a9e68eb5aba18e4c3b341cbef2d018b2da0/{CPU_AI_FILE}")
CPU_AI_SIZE_MB = 1650
# The languages each AI translator reads better than the fast translator (by 1 chrF or more), MEASURED
# on FLORES-101: 60 professionally translated sentences in each of 34 languages, into English, chrF
# against the human English. A book in any other language is read by the fast translator, which did as
# well or better there (Arabic, Hindi, Turkish, Polish, Dutch, Greek, Irish, Maltese ...).
GPU_AI_LANGS = {"en", "ja", "zh", "ko", "es", "fr", "de", "it", "pt", "ru", "lv", "cs", "hu"}     # Qwen3-4B
CPU_AI_LANGS = {"en", "zh", "fr", "pt", "lv", "sl", "hu", "gl"}                                 # EuroMoE
_card = None


def graphics_card():
    """A graphics card with memory of its own enough for Qwen3-4B (3.5 GB or more; built-in laptop
    graphics share the computer's memory and report far less)."""
    global _card
    if _card is None:
        _card = False
        try:
            import subprocess
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "(Get-CimInstance Win32_VideoController).AdapterRAM"],
                                 capture_output=True, text=True, timeout=20, creationflags=0x08000000).stdout
            _card = any(int(v) >= 3.5e9 for v in out.split() if v.strip().isdigit())
        except Exception:
            pass
    return _card


def ai_knows(lang, target, gpu=None):
    """The AI translator reads this book better than the fast translator would: both the book's
    language and the one it is read in are among its measured languages (GPU_AI_LANGS, CPU_AI_LANGS)."""
    langs = GPU_AI_LANGS if (graphics_card() if gpu is None else gpu) else CPU_AI_LANGS
    return (lang or "")[:2] in langs and (target or "")[:2] in langs


def ai_size_mb():
    return AI_SIZE_MB if graphics_card() else CPU_AI_SIZE_MB
# the fast translator (NLLB-200 distilled 600M, 8-bit CTranslate2; CC BY-NC 4.0) is built in; this copy on
# BookTalker's GitHub release is fetched only if it's missing (and serves anyone building from source)
REPO = "NealStrassner/BookTalker"
TRANSLATOR_DIR = "nllb-600m-int8"
TRANSLATOR_URL = f"https://github.com/{REPO}/releases/download/models-1/nllb-200-distilled-600M-int8.zip"
TRANSLATOR_SIZE_MB = 600


def packs_dir(*parts):
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    if package_family():
        # the Microsoft Store copy: Windows keeps its AppData in its package's own folder, and a
        # program started through the redirected path can't find the libraries beside it
        # (llama-server-impl.dll), so the same files are named by where they really are
        base = os.path.join(base, "Packages", package_family(), "LocalCache", "Local")
    return os.path.join(base, "BookTalker", "packs", *parts)


def find(*parts):
    """A model file: bundled with the app, else downloaded as a pack, else None."""
    for p in (resource(*parts), packs_dir(*parts)):
        if os.path.exists(p):
            return p
    return None


def ai_installed():
    return bool((find("models", "qwen", AI_MODEL_FILE) and find("engines", "llama", "vulkan", "llama-server.exe"))
                or (find("models", "euromoe", CPU_AI_FILE) and find("engines", "llama", "cpu", "llama-server.exe")))


def translator_dir():
    """The fast translator's folder (bundled in a development copy, else downloaded), or None."""
    p = find("models", TRANSLATOR_DIR, "model.bin")
    return os.path.dirname(p) if p else None


def translator_items():
    return [] if translator_dir() else [(TRANSLATOR_URL, packs_dir("models", TRANSLATOR_DIR), "dir")]


# the Lithuanian voice's stress dictionary (3 MB, piper1-gpl's own files: dictionary CC BY 4.0, the rest
# GPL-3.0), fetched with that voice from the repository at the version BookTalker was tested with
LITHUANIAN_URL = ("https://raw.githubusercontent.com/OHF-voice/piper1-gpl/9b64bfcc0cb8b4243fa3e963915589c24762b872/"
                  "src/piper/lithuanian/{name}")
LITHUANIAN_FILES = ("lt_kirciai.tsv", "lt_kreipiniai.tsv", "lt_raides.tsv", "LICENSE", "SOURCE")


def lithuanian_dir():
    """The Lithuanian stress dictionary's folder (downloaded, or in a development copy), or None."""
    for d in (packs_dir("lithuanian"), resource("bt", "piperx", "lithuanian")):
        if all(os.path.exists(os.path.join(d, f)) for f in LITHUANIAN_FILES[:3]):
            return d
    return None


def lithuanian_items():
    return [] if lithuanian_dir() else [(LITHUANIAN_URL.format(name=f), packs_dir("lithuanian", f), False)
                                        for f in LITHUANIAN_FILES]


PINYIN_VOICES = {"zh_CN-chaowen-medium", "zh_CN-xiao_ya-medium"}
G2PW_URL = "https://huggingface.co/datasets/rhasspy/piper-checkpoints/resolve/main/zh/zh_CN/_resources/g2pw.tar.gz?download=true"
BERT_VOCAB_URL = "https://huggingface.co/google-bert/bert-base-chinese/resolve/main/vocab.txt"
# g2pW's three lookup tables (the package itself is never imported; Apache-2.0)
G2PW_TABLES_URL = ("https://files.pythonhosted.org/packages/d0/5d/12ab1e62f4d9bc2dcd4dfaf599047eacd87988f5c2f1b011fbfacb19673d/"
                   "g2pw-0.1.1-py3-none-any.whl")
G2PW_TABLES = ("bopomofo_to_pinyin_wo_tune_dict.json", "char_bopomofo_dict.json", "bert-base-chinese_s2t_dict.txt")

# the Thai voice pronounces through TLTK (Chulalongkorn University, BSD-3-Clause): only its
# pronunciation part and the dictionaries that part reads are kept (see piperx.load_tltk)
THAI_VOICES = {"th_TH-tsync2-medium"}
TLTK_URL = ("https://files.pythonhosted.org/packages/f6/e9/9ed422db47a19186d76f72e4da5b2aa5ac49e12d790e5dd6ce83c8acc576/"
            "tltk-1.11-py3-none-any.whl")
TLTK_FILES = ("nlp.py", "sylrule.lts", "thaisyl.dict", "sylseg.3g", "thdict", "sylform_var.pklz",
              "PhSTrigram.sts", "word.pklz", "LICENSE.txt")


def voice_url(stem):
    loc, name, quality = stem.split("-")
    return VOICE_URL.format(lang=loc.split("_")[0], loc=loc, name=name, quality=quality, stem=stem)


def _ssl():
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT       # some antivirus TLS proxies fail strict checks
    return ctx


class Download(threading.Thread):
    """Fetch a list of (url, destination, unzip) items. on_progress(done_bytes, total_bytes);
    on_done(error_or_None). Files land as .part and are renamed only when complete."""

    def __init__(self, items, on_progress, on_done):
        super().__init__(daemon=True)
        self.items, self.on_progress, self.on_done = items, on_progress, on_done
        self.canceled = False

    def run(self):
        ctx = _ssl()
        try:
            sizes = []
            for url, _, _ in self.items:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "BookTalker"})
                with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
                    sizes.append(int(r.headers.get("Content-Length") or 0))
            total, done = sum(sizes), 0
            for url, dest, unzip in self.items:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                req = urllib.request.Request(url, headers={"User-Agent": "BookTalker"})
                # (a big folder zip goes to disk, not memory: the translator's is 600 MB)
                buf = (open(dest + ".zip.part", "wb") if unzip == "dir" else
                       io.BytesIO() if unzip else open(dest + ".part", "wb"))
                with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
                    while True:
                        if self.canceled:
                            raise RuntimeError("canceled")
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        buf.write(chunk)
                        done += len(chunk)
                        self.on_progress(done, total)
                if unzip == "dir":      # a whole folder (the fast translator): unpacked aside, then moved in
                    import shutil
                    buf.close()
                    tmp = dest + ".unzip"
                    shutil.rmtree(tmp, ignore_errors=True)
                    os.makedirs(tmp)
                    with zipfile.ZipFile(dest + ".zip.part") as z:
                        for name in z.namelist():
                            base = os.path.basename(name)
                            if base:
                                with z.open(name) as src, open(os.path.join(tmp, base), "wb") as f:
                                    shutil.copyfileobj(src, f, 1 << 20)
                    os.remove(dest + ".zip.part")
                    shutil.rmtree(dest, ignore_errors=True)
                    os.replace(tmp, dest)
                elif unzip == "tables":   # g2pW's lookup tables, out of its package
                    z = zipfile.ZipFile(buf)
                    os.makedirs(dest, exist_ok=True)
                    for name in z.namelist():
                        if os.path.basename(name) in G2PW_TABLES:
                            with open(os.path.join(dest, os.path.basename(name)), "wb") as f:
                                f.write(z.read(name))
                elif unzip == "tltk":   # TLTK's pronunciation part, as a package of its own
                    z = zipfile.ZipFile(buf)
                    os.makedirs(dest, exist_ok=True)
                    for name in z.namelist():
                        if os.path.basename(name) in TLTK_FILES:
                            with open(os.path.join(dest, os.path.basename(name)), "wb") as f:
                                f.write(z.read(name))
                    with open(os.path.join(dest, "__init__.py"), "w") as f:
                        f.write("")     # not TLTK's own: that one loads its corpus tools
                elif unzip == "tar":    # g2pW: the whole archive into its folder
                    import tarfile
                    buf.seek(0)
                    os.makedirs(dest, exist_ok=True)
                    with tarfile.open(fileobj=buf, mode="r:gz") as t:
                        t.extractall(dest, filter="data")
                elif unzip:   # llama.cpp: keep the server and the libraries it loads
                    z = zipfile.ZipFile(buf)
                    os.makedirs(dest, exist_ok=True)
                    for name in z.namelist():
                        base = os.path.basename(name)
                        if base and (base == "llama-server.exe" or base.lower().endswith(".dll")):
                            with open(os.path.join(dest, base), "wb") as f:
                                f.write(z.read(name))
                else:
                    buf.close()
                    os.replace(dest + ".part", dest)
            self.on_done(None)
            from . import update
            update.fix_listing()            # (Windows' list of programs shows the new size)
        except Exception as e:      # noqa: BLE001 — reported to the user
            self.on_done(str(e) or e.__class__.__name__)


def ai_items():
    """Qwen3-4B for a graphics card, or EuroMoE for the processor (only what this computer can run)."""
    if graphics_card():
        items = [(AI_MODEL_URL, packs_dir("models", "qwen", AI_MODEL_FILE), False),
                 (LLAMA_URL.format(tag=LLAMA_TAG, kind="vulkan"), packs_dir("engines", "llama", "vulkan"), True)]
    else:
        items = [(CPU_AI_URL, packs_dir("models", "euromoe", CPU_AI_FILE), False),
                 (LLAMA_URL.format(tag=LLAMA_TAG, kind="cpu"), packs_dir("engines", "llama", "cpu"), True)]
    # the fast translator reads while the AI starts, for languages EuroMoE doesn't know, and if the
    # AI can't run after all - so it always comes along
    return items + translator_items()


def remove_ai():
    """Delete the best translator's model and engine (the fast translator stays). OSError while
    its engine is still running."""
    import shutil
    for p in (packs_dir("models", "qwen"), packs_dir("models", "euromoe"), packs_dir("engines", "llama")):
        if os.path.isdir(p):
            shutil.rmtree(p)


def voice_items(stem):
    from . import kokoro
    if stem in kokoro.VOICES:           # its style file, and the shared model if it isn't here yet
        vid = kokoro.VOICES[stem][0]
        items = [(kokoro.VOICE_URL.format(id=vid), packs_dir("kokoro", "voices", vid + ".bin"), False)]
        if not os.path.exists(packs_dir("kokoro", "model.onnx")):
            items.insert(0, (kokoro.MODEL_URL, packs_dir("kokoro", "model.onnx"), False))
        return items
    url = voice_url(stem)
    items = [(url, packs_dir("voices", stem + ".onnx"), False),
             (url + ".json", packs_dir("voices", stem + ".onnx.json"), False)]
    if stem in PINYIN_VOICES and not all(os.path.exists(packs_dir("g2pW", f)) for f in ("g2pw.onnx",) + G2PW_TABLES):
        # these Chinese voices pronounce through the g2pW model (113 MB, from Piper's own repository)
        # and BERT's Chinese word list: fetched now, with the voice, never in the middle of reading
        items += [(G2PW_URL, packs_dir("g2pW"), "tar"), (BERT_VOCAB_URL, packs_dir("g2pW", "bert-vocab.txt"), False),
                  (G2PW_TABLES_URL, packs_dir("g2pW"), "tables")]
    if stem in THAI_VOICES and not all(os.path.exists(packs_dir("tltk", "tltk", f)) for f in TLTK_FILES):
        items.append((TLTK_URL, packs_dir("tltk", "tltk"), "tltk"))     # 20 MB
    if stem.startswith("lt_"):
        items += lithuanian_items()
    return items
