"""Stage 3 — speech. Piper voice with per-word timing for on-page highlighting.

Piper reports how many audio samples each phoneme takes. Each word is phonemized on
its own too, and the two phoneme strings are matched up, so every phoneme of the
sentence is owned by one word -> word start/end times in samples.
"""
import difflib

import numpy as np
from piper import PiperVoice, SynthesisConfig

STRIP = set("ˈˌ ,.;:!?¡¿—–-…\"'()[]")
VOWELS = set("aeiouyæɑɐɒɔəɛɜɚɝɪʊʌᵻœøɨʉɵɘɞɤɯ")
SILENT = set("ːˑʲ̃")


OUT_RATE = 22050


def _packs():
    """Where a voice finds what it downloaded with it (the Chinese g2pW model)."""
    from .packs import packs_dir
    return packs_dir()


def _resample(a, src, dst):
    """Audio from src Hz to dst Hz (speech: a short average against aliasing, then interpolation)."""
    if src == dst or not len(a):
        return a
    if src > dst:
        k = max(1, int(round(src / dst)))
        a = np.convolve(a, np.ones(k, np.float32) / k, mode="same")
    n = int(round(len(a) * dst / src))
    return np.interp(np.arange(n) * (src / dst), np.arange(len(a)), a).astype(np.float32)


def skeleton(ph):
    """Phonemes compared loosely: unstressed vowels shift in running speech
    ("to" = tuː alone, tə in a sentence), consonants don't."""
    return ["V" if c in VOWELS else c for c in ph if c not in SILENT]


class Speaker:
    def __init__(self, model_path):
        from . import piperx
        piperx.install()                # Lithuanian and Chinese 'pinyin' voices (bt/piperx)
        if model_path.endswith(".ort"):
            # prepared by tools/prepare_voices.py: alignment output already built in
            self.voice = PiperVoice.load(model_path, config_path=model_path[:-4] + ".onnx.json", download_dir=_packs())
        else:
            self.voice = PiperVoice.load(model_path, include_alignments=True, download_dir=_packs())
        # every voice is played at 22050 Hz; the few recorded at another rate (French 'tom' at
        # 44100, the Kazakh voices at 16000) are converted, or they'd play slow and deep / fast
        self.native_rate = self.voice.config.sample_rate
        self.rate = OUT_RATE
        self._word_cache = {}

    def _word_phonemes(self, say):
        ph = self._word_cache.get(say)
        if ph is None:
            ph = [c for sent in self.voice.phonemize(say) for c in sent if c not in STRIP]
            self._word_cache[say] = ph
        return ph

    def speak(self, sentence, speed=1.0):
        """-> (float32 audio, [(start, end) or None per word]) for a reflow.Sentence."""
        says = [w.say for w in sentence.words]
        text = " ".join(s for s in says if s)
        cfg = SynthesisConfig(length_scale=1.0 / speed)
        audio_parts, phon, starts, ends = [], [], [], []
        offset = 0
        for chunk in self.voice.synthesize(text, syn_config=cfg, include_alignments=True):
            a = chunk.audio_float_array
            al = chunk.phoneme_alignments
            if al and len(al) == len(chunk.phonemes) + 2:
                pos = offset + al[0].num_samples              # skip BOS
                for ph, item in zip(chunk.phonemes, al[1:-1]):
                    phon.append(ph)
                    starts.append(pos)
                    pos += item.num_samples
                    ends.append(pos)
            else:
                # No alignment for this chunk: spread its phonemes evenly.
                step = len(a) / max(1, len(chunk.phonemes))
                for k, ph in enumerate(chunk.phonemes):
                    phon.append(ph)
                    starts.append(offset + int(k * step))
                    ends.append(offset + int((k + 1) * step))
            audio_parts.append(a)
            offset += len(a)
        audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, np.float32)
        times = self._word_times(says, phon, starts, ends)
        if self.native_rate != OUT_RATE:
            k = OUT_RATE / self.native_rate
            audio = _resample(audio, self.native_rate, OUT_RATE)
            times = [(int(t[0] * k), int(t[1] * k)) if t else t for t in times]
        pause = np.zeros(int(sentence.pause * self.rate), np.float32)
        return np.concatenate([audio, pause]).astype(np.float32), times

    def _word_times(self, says, phon, starts, ends):
        """Assign the sentence's phonemes to its words.

        The voice's own word breaks (spaces in its phoneme stream) are the main guide.
        A word-level alignment handles the places where they differ from the printed
        words: numbers spoken as several words ("1000" -> "one thousand") and short
        words run together ("that the" -> one phoneme word).
        """
        # Phoneme words: lists of indices into phon (letters only).
        pw, cur = [], []
        for i, c in enumerate(phon):
            if c == " ":
                if cur:
                    pw.append(cur)
                    cur = []
            elif c not in STRIP:
                cur.append(i)
        if cur:
            pw.append(cur)
        words = [wi for wi, s in enumerate(says) if s]
        wq = [skeleton(self._word_phonemes(says[wi])) for wi in words]
        sk = {x: skeleton(phon[x]) for w in pw for x in w}       # per phoneme: [] or [c]
        times = [None] * len(says)
        if not words or not pw:
            return times
        n, m = len(words), len(pw)
        moves = ((1, 1), (1, 2), (1, 3), (1, 4), (2, 1), (3, 1), (1, 0), (0, 1))
        INF = float("inf")
        cost = [[INF] * (m + 1) for _ in range(n + 1)]
        back = [[None] * (m + 1) for _ in range(n + 1)]
        cost[0][0] = 0.0
        for i in range(n + 1):
            for j in range(m + 1):
                c0 = cost[i][j]
                if c0 == INF:
                    continue
                for a, b in moves:
                    if i + a > n or j + b > m:
                        continue
                    if a == 0 or b == 0:
                        step = 1.0                     # word with no sound / stray sound
                    else:
                        q = [c for k in range(i, i + a) for c in wq[k]]
                        p = [c for k in range(j, j + b) for x in pw[k] for c in sk[x]]
                        step = 1.0 - difflib.SequenceMatcher(None, q, p, autojunk=False).ratio()
                        step += 0.35 * (a + b - 2)     # prefer one-to-one
                    if c0 + step < cost[i + a][j + b]:
                        cost[i + a][j + b] = c0 + step
                        back[i + a][j + b] = (a, b)
        i, j, pairs = n, m, []
        while i or j:
            a, b = back[i][j]
            pairs.append((i - a, a, j - b, b))
            i, j = i - a, j - b
        for i0, a, j0, b in reversed(pairs):
            if a == 0 or b == 0:
                continue
            idx = [x for k in range(j0, j0 + b) for x in pw[k]]
            if a == 1:
                times[words[i0]] = (starts[idx[0]], ends[idx[-1]])
                continue
            # Several printed words in one phoneme word: split it by sound matching.
            q, owner = [], []
            for k in range(i0, i0 + a):
                q.extend(wq[k])
                owner.extend([k] * len(wq[k]))
            own = [None] * len(idx)
            sm = difflib.SequenceMatcher(None, [(sk[x] or ["ː"])[0] for x in idx], q,
                                         autojunk=False)
            for pa, qb, size in sm.get_matching_blocks():
                for k in range(size):
                    own[pa + k] = owner[qb + k]
            last = i0
            for k in range(len(own)):
                if own[k] is None or own[k] < last:
                    own[k] = last
                last = own[k]
            for k, wk in enumerate(own):
                wi = words[wk]
                x = idx[k]
                times[wi] = (starts[x], ends[x]) if times[wi] is None else (times[wi][0], ends[x])
        return times
