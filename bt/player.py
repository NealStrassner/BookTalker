"""Playback: a synthesis thread keeps a few sentences ready (translating them first when
reading a translation); the audio callback plays them and tracks the sample position so
the UI can highlight the word being spoken."""
import collections
import threading
import time

import sounddevice as sd

from .reflow import Sentence, Word

AHEAD = 3   # sentences prepared ahead of the one playing


class Player:
    def __init__(self, get_speaker, book, translator, voice, translate=False, src_code=None, lang=None):
        """book.next_after(key) -> Sentence | None (end) | "wait" (not ready yet)
        book.get(key) -> Sentence | None | "wait"
        get_speaker(voice) -> speech.Speaker
        translator: llm.SmartTranslator (AI, working ahead; NLLB fallback)"""
        self.get_speaker = get_speaker
        self.book = book
        self.translator = translator
        self.voice = voice
        self.translate = translate
        self.src_code = src_code
        self.lang = lang
        self.last_engine = None             # "ai" or "fast": which translator made the last sentence
        self.rate = 22050                   # every bundled voice; no need to load one here
        self.speed = 1.0
        self.volume = 1.0                   # the sleep timer fades out with it
        self.lock = threading.Lock()
        self.queue = collections.deque()    # (sentence, audio, times, spoken_words)
        self.cur = None                     # item now playing
        self.pos = 0                        # sample position within cur
        self.paused = True
        self.gen = 0                        # bumps on every seek; stale output is dropped
        self.start_key = None
        self.finished = False
        self.lengths = {}                   # sentence key -> seconds of audio (for rewinding)
        self.wake = threading.Event()
        self.stream = sd.OutputStream(samplerate=self.rate, channels=1, dtype="float32",
                                      callback=self._callback, blocksize=1024)
        self.stream.start()
        threading.Thread(target=self._synth_loop, daemon=True).start()

    # ---- control -------------------------------------------------------------
    def play_from(self, key):
        with self.lock:
            self.gen += 1
            self.queue.clear()
            self.cur = None
            self.pos = 0
            self.start_key = key
            self.finished = False
            self.paused = False
        if self.translate:
            self.translator.follow(self.book, key, self.lang, self.src_code)
        self.wake.set()

    def set_paused(self, paused):
        self.paused = paused

    def _restart_here(self):
        key = self.current_key()
        if key is not None:
            paused = self.paused
            self.play_from(key)
            self.paused = paused

    def set_speed(self, speed):
        self.speed = speed
        self._restart_here()

    def set_mode(self, voice, translate, src_code, lang=None):
        """Switch voice and/or original-vs-translation; carries on from the same sentence.
        (All bundled voices are 22050 Hz, so the audio stream stays as it is; the new
        voice loads in the synthesis thread, not here.)"""
        self.voice, self.translate, self.src_code = voice, translate, src_code
        self.lang = lang or self.lang
        self._restart_here()

    def seconds_into_current(self):
        with self.lock:
            return self.pos / self.rate if self.cur else 0.0

    def current_key(self):
        with self.lock:
            if self.cur:
                return self.cur[0].key
            if self.queue:
                return self.queue[0][0].key
            return self.start_key

    def state(self):
        """-> (sentence, index of the word being heard or None, the words being spoken)"""
        with self.lock:
            cur, pos = self.cur, self.pos
        if cur is None:
            return None, None, None
        sentence, audio, times, spoken = cur
        heard = pos - int(self.stream.latency * self.rate)   # what reaches the speakers now
        idx = None
        for i, t in enumerate(times):
            if t is not None and t[0] <= heard:
                idx = i
        return sentence, idx, spoken

    def close(self):
        self.gen += 1
        self.stream.stop()
        self.stream.close()

    # ---- threads -------------------------------------------------------------
    def _render(self, sentence):
        speaker = self.get_speaker(self.voice)
        if sentence.literal or not (self.translate or sentence.code):
            audio, times = speaker.speak(sentence, self.speed)
            self._check_pace(sentence, audio)
            return audio, times, sentence.words
        # wait for the AI only as long as the audio already queued lasts
        with self.lock:
            queued = sum(len(item[1]) for item in self.queue)
            if self.cur is not None:
                queued += max(0, len(self.cur[1]) - self.pos)
        buffered = queued / self.rate
        # a short pause between sentences beats switching translators mid-passage
        wait = 10.0 if buffered < 0.5 else buffered + 1.5
        if sentence.code:               # a piece of code, explained (the code stays highlighted)
            from .code import spoken_text
            text = spoken_text(sentence, self.translator, self.translator.target if self.translate else self.lang, wait)
        else:
            text, self.last_engine = self.translator.get(sentence, self.src_code, wait)
        words = [Word(t, t, []) for t in text.split()]
        spoken = Sentence(key=sentence.key, words=words, pause=sentence.pause, page=sentence.page)
        audio, times = speaker.speak(spoken, self.speed)
        return audio, times, words

    def _check_pace(self, sentence, audio):
        """A sentence spoken far faster than speech can be (a reader heard a voice 'saying only
        half of each word' once; not reproduced): note it in error.log to find the cause."""
        text = " ".join(w.say for w in sentence.words if w.say)
        seconds = len(audio) / self.rate - sentence.pause
        letters = sum(c.isalpha() for c in text)
        if letters >= 40 and seconds * self.speed < 0.025 * letters:     # normal speech: ~0.06 s a letter
            import os
            import time as _t
            try:
                d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BookTalker")
                with open(os.path.join(d, "error.log"), "a", encoding="utf-8") as f:
                    f.write(f"{_t.strftime('%Y-%m-%d %H:%M:%S')}  speech too fast: voice {self.voice}, speed "
                            f"{self.speed}, {seconds:.2f} s for {letters} letters: {text[:200]}\n")
            except OSError:
                pass

    def _callback(self, out, frames, _time, _status):
        out.fill(0)
        if self.paused:
            return
        filled = 0
        with self.lock:
            while filled < frames:
                if self.cur is None:
                    if not self.queue:
                        break
                    self.cur, self.pos = self.queue.popleft(), 0
                audio = self.cur[1]
                n = min(frames - filled, len(audio) - self.pos)
                out[filled:filled + n, 0] = audio[self.pos:self.pos + n]
                filled += n
                self.pos += n
                if self.pos >= len(audio):
                    if self.queue:
                        self.cur, self.pos = self.queue.popleft(), 0
                    else:
                        break       # hold on the finished sentence until the next is ready
        if self.volume < 1.0:
            out *= self.volume
        self.wake.set()

    def _synth_loop(self):
        last_key, last_gen = None, -1
        while True:
            self.wake.wait(0.1)
            self.wake.clear()
            with self.lock:
                gen = self.gen
                if gen != last_gen:
                    last_key, last_gen, pending = None, gen, self.start_key
                ready = len(self.queue) + (0 if self.cur is None else 1)
                if self.cur is not None and self.pos >= len(self.cur[1]) and self.queue:
                    ready -= 1
            if self.start_key is None or ready > AHEAD or self.finished:
                continue
            nxt = self.book.get(pending) if last_key is None else self.book.next_after(last_key)
            if nxt == "wait" or (nxt is None and last_key is None):
                time.sleep(0.2)
                continue
            if nxt is None:
                self.finished = True
                continue
            try:
                audio, times, spoken = self._render(nxt)
            except Exception:
                last_key = nxt.key          # skip a sentence the voice/translator can't handle
                continue
            with self.lock:
                if self.gen != gen:
                    continue            # a seek happened while preparing
                if self.cur is not None and self.pos >= len(self.cur[1]):
                    self.cur = None     # previous sentence finished while we waited
                self.queue.append((nxt, audio, times, spoken))
                self.lengths[nxt.key] = len(audio) / self.rate
            last_key = nxt.key
