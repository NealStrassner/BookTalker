"""Optional downloads ("packs"): extra voices and the AI translator are fetched from their
official public sources only when the user asks for them, keeping the app itself small.

    voices          huggingface.co/rhasspy/piper-voices          ~60 MB each
    AI translator   huggingface.co/bartowski (Qwen3-4B, Apache-2.0)  2.5 GB
                    github.com/ggml-org/llama.cpp (engine)         ~50 MB
"""
import io
import os
import ssl
import threading
import urllib.request
import zipfile

from .paths import resource

LLAMA_TAG = "b11404"
AI_MODEL_FILE = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
AI_MODEL_URL = f"https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/main/{AI_MODEL_FILE}"
LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/llama-{tag}-bin-win-{kind}-x64.zip"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{loc}/{name}/{quality}/{stem}.onnx"
AI_SIZE_MB = 2600
# the fast translator (NLLB-200 distilled 600M, 8-bit CTranslate2; CC BY-NC 4.0): kept as a download on
# BookTalker's own GitHub release, so readers who never translate don't carry its 623 MB
REPO = "NealStrassner/BookTalker"
TRANSLATOR_DIR = "nllb-600m-int8"
TRANSLATOR_URL = f"https://github.com/{REPO}/releases/download/models-1/nllb-200-distilled-600M-int8.zip"
TRANSLATOR_SIZE_MB = 600


def packs_dir(*parts):
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "BookTalker", "packs", *parts)


def find(*parts):
    """A model file: bundled with the app, else downloaded as a pack, else None."""
    for p in (resource(*parts), packs_dir(*parts)):
        if os.path.exists(p):
            return p
    return None


def ai_installed():
    return bool(find("models", "qwen", AI_MODEL_FILE) and find("engines", "llama", "vulkan", "llama-server.exe"))


def translator_dir():
    """The fast translator's folder (bundled in a development copy, else downloaded), or None."""
    p = find("models", TRANSLATOR_DIR, "model.bin")
    return os.path.dirname(p) if p else None


def translator_items():
    return [] if translator_dir() else [(TRANSLATOR_URL, packs_dir("models", TRANSLATOR_DIR), "dir")]


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
        self.cancelled = False

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
                        if self.cancelled:
                            raise RuntimeError("cancelled")
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
        except Exception as e:      # noqa: BLE001 — reported to the user
            self.on_done(str(e) or e.__class__.__name__)


def ai_items():
    items = [(AI_MODEL_URL, packs_dir("models", "qwen", AI_MODEL_FILE), False)]
    for kind in ("vulkan",):                    # graphics card only (see llm.LlamaEngine._start)
        items.append((LLAMA_URL.format(tag=LLAMA_TAG, kind=kind), packs_dir("engines", "llama", kind), True))
    # the AI runs only on a graphics card: the fast translator reads while it starts, when the
    # card is busy, and on computers without one - so it always comes along
    return items + translator_items()


def voice_items(stem):
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
    return items
