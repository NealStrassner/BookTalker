"""Pronunciation systems newer than the bundled Piper release (piper-tts 1.8.0), so every voice in
the catalog can speak:

    lithuanian   espeak-ng IPA + pitch-accent dictionary   (phonemize_lithuanian.py, lithuanian/:
                 from piper1-gpl's main branch, GPL-3.0; dictionary CC BY 4.0, see lithuanian/SOURCE)
    pinyin       Chinese g2pW, without the 'transformers' library: Piper only uses its BERT
                 tokenizer, replaced by bert_tokenizer.py (the g2pW model downloads with the voice)
    thai         TLTK's th2ipa, without the libraries its other tools need (load_tltk; TLTK's
                 pronunciation part downloads with the voice)

install() teaches the installed Piper these types; it changes nothing on disk.
"""
import enum
import sys
import types

_done = False

# imported by tltk/nlp.py for its tagging, parsing and text-level tools; th2ipa never calls them
_TLTK_UNUSED = {"pandas": (), "nltk": (), "nltk.tag": (), "nltk.tag.perceptron": ("PerceptronTagger",),
                "nltk.parse": ("malt",), "sklearn": (), "sklearn.ensemble": ("RandomForestClassifier",),
                "sklearn.feature_extraction": ("DictVectorizer",), "sklearn.pipeline": ("Pipeline",),
                "sklearn_crfsuite": ("CRF",)}


class _Unused:
    def __init__(self, *a, **k):
        raise RuntimeError("not part of BookTalker's TLTK")


def load_tltk():
    """Import TLTK's pronunciation part from the packs folder, where Piper's Thai voice finds it.
    Its unused imports get empty stand-ins for the length of the import only."""
    if "tltk.nlp" in sys.modules:
        return
    import os
    import warnings
    from ..packs import packs_dir
    home = packs_dir("tltk")
    if not os.path.exists(os.path.join(home, "tltk", "nlp.py")):
        raise RuntimeError("Thai pronunciation files not found in " + home)
    if home not in sys.path:
        sys.path.append(home)
    added = []
    for name, attrs in _TLTK_UNUSED.items():
        if name not in sys.modules:
            m = types.ModuleType(name)
            for a in attrs:
                setattr(m, a, _Unused)
            sys.modules[name] = m
            added.append(name)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")     # its old-style regex strings
            import tltk.nlp  # noqa: F401
    finally:
        for name in added:
            del sys.modules[name]


def install():
    global _done
    if _done:
        return
    _done = True
    import piper.config as cfg
    import piper.voice as pv
    if not hasattr(cfg.PhonemeType, "LITHUANIAN"):
        members = {m.name: m.value for m in cfg.PhonemeType}
        members["LITHUANIAN"] = "lithuanian"
        new = enum.Enum("PhonemeType", members, type=str)
        cfg.PhonemeType = new                   # PiperConfig.from_dict looks the name up here
        pv.PhonemeType = new
    original = pv.PiperVoice.phonemize

    def phonemize(self, text):
        if self.config.phoneme_type == "lithuanian":
            ph = getattr(self, "_bt_lithuanian", None)
            if ph is None:
                from .phonemize_lithuanian import LithuanianPhonemizer
                ph = self._bt_lithuanian = LithuanianPhonemizer(espeak_data_dir=self.espeak_data_dir)
            return ph.phonemize(text)
        if self.config.phoneme_type == "thai":
            load_tltk()
        return original(self, text)

    pv.PiperVoice.phonemize = phonemize
    try:                                        # Chinese 'pinyin' voices: BERT tokenizer without transformers
        import transformers  # noqa: F401
    except ImportError:
        from .bert_tokenizer import BertTokenizer
        fake = types.ModuleType("transformers")
        fake.BertTokenizer = BertTokenizer
        sys.modules["transformers"] = fake
