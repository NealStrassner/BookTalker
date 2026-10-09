"""Voices run in their own process.

onnxruntime holds Python's global lock while it sets up a voice (~4.5 s, measured), which
froze the whole window. In a separate process that can't happen, and speech synthesis no
longer competes with the interface for Python's lock either.
"""
import multiprocessing as mp
import threading

RATE = 22050        # every bundled Piper voice is 22050 Hz


class _W:
    __slots__ = ("say",)

    def __init__(self, say):
        self.say = say


class _S:
    __slots__ = ("words", "pause")

    def __init__(self, says, pause):
        self.words = [_W(s) for s in says]
        self.pause = pause


def _serve(conn):
    from .speech import Speaker
    speakers = {}
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        op = msg[0]
        try:
            if op == "load":
                _, stem, path = msg
                if stem not in speakers:
                    speakers[stem] = Speaker(path)
                conn.send(("ok", speakers[stem].rate))
            elif op == "speak":
                _, stem, says, pause, speed = msg
                audio, times = speakers[stem].speak(_S(says, pause), speed)
                conn.send(("ok", (audio, [tuple(map(int, t)) if t else None for t in times])))
            elif op == "quit":
                return
        except Exception as e:      # noqa: BLE001 — reported to the caller
            conn.send(("err", repr(e)))


class VoiceProcess:
    """One background process holding every loaded voice. Calls block the calling
    thread (never the interface thread) until the voice process answers."""

    def __init__(self):
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_serve, args=(child,), daemon=True)
        self.proc.start()
        self.lock = threading.Lock()
        self.loaded = set()

    def _call(self, *msg):
        with self.lock:
            self.conn.send(msg)
            status, value = self.conn.recv()
        if status != "ok":
            raise RuntimeError(value)
        return value

    def load(self, stem, path):
        if stem not in self.loaded:
            self._call("load", stem, path)
            self.loaded.add(stem)

    def speak(self, stem, says, pause, speed):
        return self._call("speak", stem, says, pause, speed)

    def close(self):
        try:
            with self.lock:
                self.conn.send(("quit",))
        except Exception:
            pass


class VoiceProxy:
    """Looks like speech.Speaker to the player; the work happens in the voice process."""

    def __init__(self, vp, stem):
        self.vp, self.stem, self.rate = vp, stem, RATE

    def speak(self, sentence, speed=1.0):
        return self.vp.speak(self.stem, [w.say for w in sentence.words], sentence.pause, speed)
