"""Best-quality translation: Qwen3-4B-Instruct (Apache-2.0) on llama.cpp, run as a hidden
local server. Uses the graphics card through Vulkan when it can, else the processor.

SmartTranslator works ahead of the voice in reading order, giving the model the last few
sentences and its own translations as context (names and tone stay consistent). If the AI
hasn't finished a sentence by the time the voice needs it, that sentence comes from the
fast NLLB translator instead, so reading never stalls.
"""
import ctypes
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request

from .paths import resource
from .translate import LANGS, join_text, lang_name

MODEL = ("models", "qwen", "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf")
NO_WINDOW = 0x08000000
LOOKAHEAD = 12          # sentences translated ahead of the one being read
CONTEXT = 3             # previous sentence pairs shown to the model
MIN_TOKENS_PER_S = 14   # slower than this, the AI can't keep ahead of the voice: the fast translator reads


def _kill_with_parent(proc):
    """Put the server in a Windows job object that closes when BookTalker exits,
    even if BookTalker crashes, so it never lingers holding memory."""
    try:
        k32 = ctypes.windll.kernel32
        job = k32.CreateJobObjectW(None, None)

        class LIMIT(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", LIMIT), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        info = EXT()
        info.Basic.LimitFlags = 0x2000                       # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        k32.AssignProcessToJobObject(job, int(proc._handle))
        proc._bt_job = job                                   # keep the handle alive
    except Exception:
        pass


class LlamaEngine:
    """Starts llama-server on first use. status: idle | starting | gpu | cpu | failed"""

    def __init__(self):
        self.status = "idle"
        self.proc = None
        self.port = None
        self._lock = threading.Lock()
        self.ready = threading.Event()

    def available(self):
        from .packs import ai_installed
        return ai_installed()

    def start(self):
        with self._lock:
            if self.status != "idle":
                return
            self.status = "starting"
        threading.Thread(target=self._start, daemon=True).start()

    def _launch(self, kind):
        from .packs import find
        exe = find("engines", "llama", kind, "llama-server.exe")
        model = find(*MODEL)
        if not exe or not model:
            return False
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        threads = max(2, (os.cpu_count() or 4) // 2)
        # 2048 tokens of context is plenty (one sentence + 3 earlier pairs); flash attention and
        # an 8-bit KV cache keep its memory small. Measured: CPU ready in ~3.5 s, ~11 tok/s.
        args = [exe, "-m", model, "--host", "127.0.0.1", "--port", str(self.port),
                "-c", "2048", "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "-t", str(threads),
                "--no-webui", "-ngl", "99" if kind == "vulkan" else "0",
                # read the model in rather than memory-map it: MEASURED RAM in use 3047 -> 671 MB
                # with the model on the graphics card (same speed, same answers)
                "--load-mode", "none"]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=NO_WINDOW, cwd=os.path.dirname(exe))
        _kill_with_parent(self.proc)
        deadline = time.time() + 120
        while time.time() < deadline:
            if self.proc is None or self.proc.poll() is not None:
                return False                                  # e.g. no GPU / not enough GPU memory (or closing)
            try:
                if self._get("/health").get("status") == "ok":
                    self.speed = 0
                    if self._smoke():
                        return True
                    if self.speed:              # it runs, but too slowly to read along
                        self.stop()
                        return False
            except Exception:
                pass
            time.sleep(0.4)
        self.stop()
        return False

    def _start(self):
        # Whole model on the graphics card only. On the processor it was measured too slow to
        # read along: never ahead of the voice, 2-5 s per sentence, 28 s of silence in 90 s, and it
        # slowed the fast translator to 8 s a sentence too. So without a free card -> fast mode.
        for kind, status in (("vulkan", "gpu"),):
            if self._launch(kind):
                self.status = status
                self.ready.set()
                return
            self.stop()
        self.status = "failed"
        self.ready.set()

    def _get(self, path):
        return json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5))

    def _smoke(self):
        """A short request proves the model really runs (GPU memory can fail late) and fast enough
        to keep ahead of the voice: a laptop's built-in graphics can load it and still crawl.
        MEASURED: 18 tokens/s (graphics card) keeps up; 11 (processor) fell behind -> 14."""
        body = json.dumps({"messages": [{"role": "user", "content": "Count from one to twenty in words."}],
                           "temperature": 0.0, "max_tokens": 40}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions", body,
                                     {"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=60))
        speed = (r.get("timings") or {}).get("predicted_per_second") or 0
        self.speed = speed
        return bool(r["choices"][0]["message"]["content"].strip()) and speed >= MIN_TOKENS_PER_S

    def chat(self, messages, max_tokens=300, timeout=90):
        body = json.dumps({"messages": messages, "temperature": 0.0, "top_k": 1,
                           "max_tokens": max_tokens}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions", body,
                                     {"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return r["choices"][0]["message"]["content"].strip()

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None


def _clean(text):
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    text = re.sub(r"^(english|translation)\s*:\s*", "", text, flags=re.I)
    return text.split("\n\n")[0].strip().strip('"').strip() or text


class SmartTranslator:
    """AI translation working ahead of the voice, with NLLB as the instant fallback."""

    def __init__(self, nllb):
        self.nllb = nllb
        self.engine = LlamaEngine()
        self.best = True                    # False = always use the fast translator
        self.done = {}                      # sentence key -> English (AI)
        self.order = []                     # keys in the order the AI translated them
        self.target = "en"                  # language to translate into
        self._job = None                    # (generation, book, start key, lang, nllb code)
        self._gen = 0
        self._last_asked = None
        self._cv = threading.Condition()
        threading.Thread(target=self._loop, daemon=True).start()

    def warm_up(self):
        if self.best and self.engine.available():
            self.engine.start()

    def set_target(self, target):
        """The language books are translated into (ISO code: en, es, fr ...)."""
        with self._cv:
            if target != self.target:
                self.target = target
                self._gen += 1                  # restart the look-ahead in the new language
                self._job = None
                self._cv.notify_all()

    def follow(self, book, key, lang, code):
        """Start (or restart) working ahead from this sentence."""
        with self._cv:
            self._gen += 1
            self._job = (self._gen, book, key, lang, code)
            self._last_asked = (key, self.target)
            self._cv.notify_all()
        self.warm_up()

    def get(self, sentence, code, wait=0.0):
        """This sentence in the target language: the AI's if ready within `wait` seconds,
        else the fast translator's."""
        key = (sentence.key, self.target)
        with self._cv:
            self._last_asked = key
            self._cv.notify_all()
            if self.best and self.engine.status in ("starting", "gpu", "cpu"):
                end = time.time() + wait
                while key not in self.done and time.time() < end:
                    self._cv.wait(timeout=max(0.05, end - time.time()))
            if key in self.done:
                return self.done[key], "ai"
        tgt = LANGS.get(self.target, ("eng_Latn",))[0]
        return self.nllb.translate(join_text([w.text for w in sentence.words]), code, tgt), "fast"

    def _ahead(self):
        """How many sentences the AI is ahead of the one last asked for (keys are
        (sentence key, target language))."""
        if self._last_asked in self.order:
            return len(self.order) - 1 - self.order.index(self._last_asked)
        return 0

    def _loop(self):
        while True:
            with self._cv:
                while self._job is None:
                    self._cv.wait()
                gen, book, key, lang, code = self._job
                target = self.target
            if not self.engine.ready.wait(timeout=1) or self.engine.status not in ("gpu", "cpu"):
                if self.engine.status == "failed":
                    with self._cv:
                        self._job = None
                continue
            sent = book.get(key)
            history = []
            while gen == self._gen and self.best:
                if sent == "wait":
                    time.sleep(0.3)
                    sent = book.get(key)
                    continue
                if sent is None:
                    break
                with self._cv:
                    while self._ahead() >= LOOKAHEAD and gen == self._gen:
                        self._cv.wait(timeout=1)
                if gen != self._gen:
                    break
                if sent.code or sent.literal:       # computer code is explained or read as it is, never translated
                    key = sent.key
                    sent = book.next_after(key)
                    continue
                src = join_text([w.text for w in sent.words])
                k = (sent.key, target)
                if k not in self.done:
                    try:
                        out = self._translate(src, lang, target, history)
                    except Exception:
                        out = None
                    if out:
                        with self._cv:
                            self.done[k] = out
                            self.order.append(k)
                            self._cv.notify_all()
                else:
                    with self._cv:
                        if k not in self.order:
                            self.order.append(k)
                if k in self.done:
                    history = (history + [(src, self.done[k])])[-CONTEXT:]
                key = sent.key
                sent = book.next_after(key)
            with self._cv:
                if gen == self._gen:
                    self._job = None

    def _translate(self, src, lang, target, history):
        name, into = lang_name(lang), lang_name(target)
        msgs = [{"role": "system", "content":
                 f"You are an expert literary translator. Translate the user's {name} text into "
                 f"natural, faithful {into} that keeps the author's tone and meaning. Keep names and "
                 "terms consistent with your earlier translations. Do not add names, details or "
                 f"explanations that are not in the text. Reply with the {into} translation only."}]
        for s, e in history:
            msgs += [{"role": "user", "content": s}, {"role": "assistant", "content": e}]
        msgs.append({"role": "user", "content": src})
        return _clean(self.engine.chat(msgs, max_tokens=min(500, 4 * len(src) + 60)))

    def shutdown(self):
        self.engine.stop()


def translate_titles(smart, titles, lang, src_code, target):
    """Chapter titles in the language being read. The AI, when it runs, translates them as one
    list (a title alone has no context: 'Действие первое' is 'Act One', not 'Action one');
    otherwise the fast translator, in one batch."""
    into, name = lang_name(target), lang_name(lang)
    if smart.best and smart.engine.status in ("gpu", "cpu") and titles:
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
        msgs = [{"role": "system", "content":
                 f"These are the chapter titles of a {name} book, in order. Translate each into {into} as a "
                 f"published translation would title it. Reply with exactly {len(titles)} numbered lines, "
                 "the translations only."},
                {"role": "user", "content": numbered}]
        try:
            text = _clean_list(smart.engine.chat(msgs, max_tokens=min(1500, 40 * len(titles) + 60), timeout=60))
            if len(text) == len(titles):
                return text
        except Exception:
            pass
    tgt = LANGS.get(target, ("eng_Latn",))[0]
    try:
        out = smart.nllb.translate_many(titles, src_code, tgt)
    except Exception:
        return None
    return [re.sub(r"\s+([.,;:!?])", r"\1", t).rstrip(" .") or o for t, o in zip(out, titles)]


def _clean_list(text):
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    return [re.sub(r"^\s*\d+[.)]\s*", "", l).strip() for l in text.strip().splitlines() if l.strip()]


def titles_in_steps(smart, titles, lang, src_code, target, emit):
    """Titles in the language being read: the fast translation at once, then, when the AI was
    still starting, its better one as soon as it is ready ('Action one' -> 'Act One')."""
    had_ai = smart.best and smart.engine.status in ("gpu", "cpu")
    out = translate_titles(smart, titles, lang, src_code, target)
    if out:
        emit(out)
    if had_ai or not smart.best or not smart.engine.available() or smart.engine.status == "failed":
        return
    smart.engine.start()
    if smart.engine.ready.wait(180) and smart.engine.status in ("gpu", "cpu"):
        better = translate_titles(smart, titles, lang, src_code, target)
        if better and better != out:
            emit(better)
