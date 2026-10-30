"""Kokoro voices (Kokoro-82M by hexgrad, Apache-2.0): very natural speech, with per-word timing.

The timestamped ONNX model (onnx-community) reports how long each of its sounds lasts, the
way Piper does; the sentence's sounds come from espeak-ng (the copy inside Piper), turned into
Kokoro's own symbols with the table of misaki, Kokoro's pronouncer (Apache-2.0). Words are then
matched to the printed text exactly as for Piper voices (speech.Speaker._word_times).

One shared model file (325 MB) and a small style file per voice (0.5 MB). MEASURED on a Ryzen
5 3600: about 2x real time on the processor with as many threads as cores (twice that is
slower: 1.1x); the smaller model files sound clearly different (spectral distance 0.5 against
the full model's; fp16: 0.1 but slower), so the full one is used.
"""
import os
import re

import numpy as np

from .speech import OUT_RATE, STRIP, Speaker, _resample

MODEL_URL = "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX-timestamped/resolve/main/onnx/model.onnx"
VOICE_URL = "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX-timestamped/resolve/main/voices/{id}.bin"
MODEL_MB = 325
RATE = 24000
MAX_TOKENS = 400        # a call takes 510 at most; longer sentences are read in parts, split between words

# stem -> (Kokoro's voice, language, country, name, gender): its best-rated voices (VOICES.md)
VOICES = {
    "en_US-heart-kokoro": ("af_heart", "en", "United States", "Heart", "woman"),
    "en_US-bella-kokoro": ("af_bella", "en", "United States", "Bella", "woman"),
    "en_US-michael-kokoro": ("am_michael", "en", "United States", "Michael", "man"),
    "en_US-fenrir-kokoro": ("am_fenrir", "en", "United States", "Fenrir", "man"),
    "en_GB-emma-kokoro": ("bf_emma", "en", "Great Britain", "Emma", "woman"),
    "en_GB-george-kokoro": ("bm_george", "en", "Great Britain", "George", "man"),
    "es_ES-dora-kokoro": ("ef_dora", "es", "", "Dora", "woman"),
    "es_ES-alex-kokoro": ("em_alex", "es", "", "Alex", "man"),
    "fr_FR-siwis-kokoro": ("ff_siwis", "fr", "", "Siwis", "woman"),
    "it_IT-sara-kokoro": ("if_sara", "it", "", "Sara", "woman"),
    "it_IT-nicola-kokoro": ("im_nicola", "it", "", "Nicola", "man"),
    "pt_BR-dora-kokoro": ("pf_dora", "pt", "Brazil", "Dora", "woman"),
    "pt_BR-alex-kokoro": ("pm_alex", "pt", "Brazil", "Alex", "man"),
    "hi_IN-alpha-kokoro": ("hf_alpha", "hi", "", "Alpha", "woman"),
    "hi_IN-omega-kokoro": ("hm_omega", "hi", "", "Omega", "man"),
}
# Kokoro's first letter -> the espeak-ng voice that pronounces for it (as misaki does)
ESPEAK = {"a": "en-us", "b": "en-gb-x-rp", "e": "es", "f": "fr", "h": "hi", "i": "it", "p": "pt-br"}

# Kokoro's symbols and their numbers (its tokenizer.json)
_SYMS = ("$;:,.!?—…\"()“” ̃ʣʥʦʨᵝꭧAIOQSTWYᵊabcdefhijklmnopqrstuvwxyzɑɐɒæβɔɕçɖðʤəɚɛɜɟɡɥɨɪʝɯɰŋɳɲɴøɸθœɹɾɻ"
         "ʁɽʂʃʈʧʊʋʌɣɤχʎʒʔˈˌːʰʲ↓→↗↘ᵻ")
_IDS = (0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 31, 33, 35, 36, 39,
        41, 42, 43, 44, 45, 46, 47, 48, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68,
        69, 70, 71, 72, 75, 76, 77, 78, 80, 81, 82, 83, 85, 86, 87, 90, 92, 99, 101, 102, 103, 110, 111, 112, 113,
        114, 115, 116, 118, 119, 120, 123, 125, 126, 128, 129, 130, 131, 132, 133, 135, 136, 138, 139, 140, 142,
        143, 147, 148, 156, 157, 158, 162, 164, 169, 171, 172, 173, 177)
VOCAB = dict(zip(_SYMS, _IDS))

# espeak-ng's sounds -> Kokoro's (misaki/espeak.py). Piper's espeak writes no tie marks; in its
# output these pairs only ever stand for the joined sound, and a stress mark never splits one.
_EN = sorted({"ʔˌn̩": "ʔn", "ʔn̩": "ʔn", "aɪ": "I", "aʊ": "W", "dʒ": "ʤ", "eɪ": "A", "e": "A",
              "tʃ": "ʧ", "ɔɪ": "Y", "ʲo": "jo", "ʲə": "jə", "ʲ": "", "ɚ": "əɹ", "r": "ɹ", "x": "k", "ç": "k",
              "ɐ": "ə", "ɬ": "l", "̃": ""}.items(), key=lambda kv: -len(kv[0]))
_OTHER = sorted({"aɪ": "I", "aʊ": "W", "dz": "ʣ", "dʒ": "ʤ", "eɪ": "A", "oʊ": "O", "əʊ": "Q", "ts": "ʦ",
                 "tʃ": "ʧ", "ɔɪ": "Y"}.items(), key=lambda kv: -len(kv[0]))


def to_kokoro(ps, kind):
    """One word's espeak sounds in Kokoro's symbols (kind: Kokoro's first letter)."""
    if kind in "ab":
        for old, new in _EN:
            ps = ps.replace(old, new)
        ps = re.sub(r"(\S)̩", r"ᵊ\1", ps).replace("̩", "")
        if kind == "b":
            ps = ps.replace("iə", "ɪə").replace("əʊ", "Q")
        else:
            ps = ps.replace("oʊ", "O").replace("ɜːɹ", "ɜɹ").replace("ɜː", "ɜɹ").replace("ɪə", "iə").replace("ː", "")
        ps = ps.replace("o", "ɔ").replace("ɾ", "T").replace("ʔ", "t")
        if ps.startswith("I") and not any(c in ps for c in "ˈˌ"):
            ps = "ˈ" + ps     # the pronoun I: espeak leaves it unstressed and Kokoro then all but drops it (MEASURED 0.03 s)
        return ps.replace("ɹɹ", "ɹ")              # (a linking r after r-colored ə, 'sister on')
    for old, new in _OTHER:
        ps = ps.replace(old, new)
    return ps.replace("-", "")


_sessions = {}          # model path -> one onnxruntime session for every Kokoro voice


def _session(path):
    if path not in _sessions:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, (os.cpu_count() or 2) // 2)    # one a core (see above)
        _sessions[path] = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    return _sessions[path]


class KokoroSpeaker(Speaker):
    """A Kokoro voice, used like speech.Speaker: speak(sentence, speed) -> (audio, word times)."""

    def __init__(self, style_path):
        from piper import espeakbridge
        from piper.phonemize_espeak import ESPEAK_DATA_DIR
        self.espeak = espeakbridge
        espeakbridge.initialize(str(ESPEAK_DATA_DIR))
        self.kind = os.path.basename(style_path)[0]
        self.lang = ESPEAK[self.kind]
        self.style = np.fromfile(style_path, dtype=np.float32).reshape(-1, 1, 256)
        model = os.path.join(os.path.dirname(os.path.dirname(style_path)), "model.onnx")
        self.sess = _session(model)
        self.native_rate = RATE
        self.rate = OUT_RATE
        self._word_cache = {}
        self._run([VOCAB["ə"]] * 8, 1.0)                    # (the first call is slow: made now)

    def _phonemes(self, text):
        """espeak-ng's sounds for the text: [(word, punctuation after it or '')]."""
        self.espeak.set_voice(self.lang)
        out = []
        for ps, term, _end in self.espeak.get_phonemes(text):
            ps = re.sub(r"\([^)]+\)", "", ps)                  # (language-switch flags)
            words = ps.split()
            out += [(w, "") for w in words]
            if out and term:
                out[-1] = (out[-1][0], term)
        return out

    def _word_phonemes(self, say):
        ph = self._word_cache.get(say)
        if ph is None:
            ph = [c for w, _t in self._phonemes(say) for c in w if c not in STRIP]
            self._word_cache[say] = ph
        return ph

    def _run(self, ids, speed):
        n = min(len(ids), len(self.style) - 1)
        wav, dur = self.sess.run(None, dict(input_ids=np.array([[0, *ids, 0]], dtype=np.int64),
                                            style=self.style[n], speed=np.array([speed], dtype=np.float32)))
        return wav[0].astype(np.float32), dur[0]

    def speak(self, sentence, speed=1.0):
        says = [w.say for w in sentence.words]
        text = " ".join(s for s in says if s)
        words = self._phonemes(text)
        # Kokoro's tokens, each knowing its espeak word; parts of at most MAX_TOKENS, split between words
        parts, ids, owner = [], [], []
        for k, (w, term) in enumerate(words):
            tok = [VOCAB[c] for c in to_kokoro(w, self.kind) + term if c in VOCAB]
            if ids and len(ids) + 1 + len(tok) > MAX_TOKENS:
                parts.append((ids, owner))
                ids, owner = [], []
            if ids:
                ids.append(VOCAB[" "])
                owner.append(None)
            ids += tok
            owner += [k] * len(tok)
        if ids:
            parts.append((ids, owner))
        audio, span, offset = [], [None] * len(words), 0
        for ids, owner in parts:
            wav, dur = self._run(ids, speed)
            spu = len(wav) / max(1e-6, float(dur.sum()))      # samples a duration unit (~600)
            pos = offset + dur[0] * spu                       # (the start token's silence)
            for k, d in zip(owner, dur[1:-1]):
                end = pos + d * spu
                if k is not None:
                    span[k] = (span[k][0], end) if span[k] else (pos, end)
                pos = end
            audio.append(wav)
            offset += len(wav)
        audio = np.concatenate(audio) if audio else np.zeros(0, np.float32)
        # each espeak sound of a word spread over the word's time, for the word matching
        phon, starts, ends = [], [], []
        for (w, _t), sp in zip(words, span):
            if phon:
                b = int(sp[0]) if sp else (ends[-1] if ends else 0)
                phon.append(" ")
                starts.append(b)
                ends.append(b)
            a, b = (sp if sp else (ends[-1] if ends else 0, ends[-1] if ends else 0))
            step = (b - a) / max(1, len(w))
            for i, c in enumerate(w):
                phon.append(c)
                starts.append(int(a + i * step))
                ends.append(int(a + (i + 1) * step))
        times = self._word_times(says, phon, starts, ends)
        k = OUT_RATE / RATE
        audio = _resample(audio, RATE, OUT_RATE)
        times = [(int(t[0] * k), int(t[1] * k)) if t else t for t in times]
        pause = np.zeros(int(sentence.pause * self.rate), np.float32)
        return np.concatenate([audio, pause]).astype(np.float32), times


def load(path):
    """The voice at path: a Kokoro style file (.bin) or a Piper model."""
    return KokoroSpeaker(path) if path.endswith(".bin") else Speaker(path)
