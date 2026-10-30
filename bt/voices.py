"""Voices: the ones on this computer, and every one BookTalker can download (Piper's, and
Kokoro's: bt/kokoro.py)."""
import glob
import os

from . import kokoro
from .paths import resource
from .voice_catalog import CATALOG as _ALL, UNSUPPORTED

CATALOG = {k: v for k, v in _ALL.items() if k not in UNSUPPORTED}   # voices that can speak here
CATALOG.update({s: (v[1], v[2], "kokoro", 1) for s, v in kokoro.VOICES.items()})

# hand-picked voice per language, with the gender we know (the catalog itself has no genders)
# file stem -> (display name, region, gender)
NAMES = {
    "en_US-lessac-medium": ("Lessac", "US", "woman"),
    "en_US-ryan-high": ("Ryan", "US", "man"),
    "en_GB-alba-medium": ("Alba", "UK", "woman"),
    "en_US-ljspeech-medium": ("LJ", "US", "woman"),
    "en_US-kristin-medium": ("Kristin", "US", "woman"),
    "en_US-joe-medium": ("Joe", "US", "man"),
    "en_US-john-medium": ("John", "US", "man"),
    "en_US-norman-medium": ("Norman", "US", "man"),
    "es_MX-claude-high": ("Claude", "México", "man"),
    "es_AR-daniela-high": ("Daniela", "Argentina", "woman"),
    "es_ES-davefx-medium": ("Davefx", "España", "man"),
    "fr_FR-siwis-medium": ("Siwis", "", "woman"),
    "de_DE-thorsten-medium": ("Thorsten", "", "man"),
    "ru_RU-irina-medium": ("Irina", "", "woman"),
    "zh_CN-huayan-medium": ("Huayan", "", "woman"),
    "it_IT-paola-medium": ("Paola", "", "woman"),
    "pt_BR-faber-medium": ("Faber", "Brasil", "man"),
}
NAMES.update({s: ("Kokoro " + v[3], "", v[4]) for s, v in kokoro.VOICES.items()})    # (region: from CATALOG)
DEFAULT_ENGLISH = "en_GB-alba-medium"     # the voice built into the app (free to share)
SHORT = {"United States": "US", "Great Britain": "UK", "Mexico": "México", "Spain": "España", "Brazil": "Brasil"}


def display_name(stem):
    if stem in NAMES:
        return NAMES[stem][0]
    parts = stem.split("-")
    name = parts[1].replace("_", " ").title() if len(parts) > 1 else stem
    return name + (" HQ" if len(parts) > 2 and parts[2] == "high" else "")


def region(stem):
    if stem in NAMES and NAMES[stem][1]:
        return NAMES[stem][1]
    country = CATALOG.get(stem, ("", ""))[1]
    return SHORT.get(country, country)


def license(stem):
    """The license of the voice's recordings ('public domain', 'CC BY 4.0', 'non-commercial' ...)."""
    from .voice_catalog import LICENSES
    return "Kokoro-82M · Apache 2.0" if is_kokoro(stem) else LICENSES.get(stem, "")


def is_kokoro(stem):
    return stem in kokoro.VOICES


def kokoro_model():
    """The shared Kokoro model file, if it has been downloaded."""
    from .packs import packs_dir
    p = packs_dir("kokoro", "model.onnx")
    return p if os.path.exists(p) else None


def size_mb(stem):
    if is_kokoro(stem):                     # its style file, and the model the first time
        return 1 + (0 if kokoro_model() else kokoro.MODEL_MB)
    return CATALOG[stem][3] if stem in CATALOG else None


def download_mb(stems):
    """What downloading these voices takes, the Kokoro model counted once."""
    mb = sum(size_mb(s) or 0 for s in stems)
    k = sum(is_kokoro(s) for s in stems)
    return mb - (k - 1) * kokoro.MODEL_MB if k > 1 and not kokoro_model() else mb


def describe(stem):
    """e.g. 'Spanish (México) · man', in the interface language."""
    from .ui.i18n import lang_label, tr
    reg = region(stem)
    gender = NAMES.get(stem, ("", "", ""))[2]
    text = lang_label(stem[:2]) + (f" ({reg})" if reg else "")
    text += f" · {tr(gender)}" if gender else ""
    return text + (" · " + tr("most natural, needs a fast computer") if is_kokoro(stem) else "")


def bundled(stem):
    """Shipped inside the app (can't be removed)."""
    return os.path.exists(resource("voices", stem + ".onnx.json"))


def installed():
    """-> {stem: {"lang": "en", "name": .., "path": ..}} — bundled voices plus
    any downloaded ones (packs)."""
    from .packs import packs_dir
    out = {}
    for folder in (resource("voices"), packs_dir("voices")):
        for cfg in sorted(glob.glob(os.path.join(folder, "*.onnx.json"))):
            stem = os.path.basename(cfg)[:-10]
            ort_path, onnx_path = cfg[:-10] + ".ort", cfg[:-5]
            p = ort_path if os.path.exists(ort_path) else onnx_path   # .ort loads twice as fast
            if not os.path.exists(p) or stem in out or stem in UNSUPPORTED:
                continue
            out[stem] = {"lang": stem[:2], "name": display_name(stem), "path": p}
    if kokoro_model():
        for stem, v in kokoro.VOICES.items():
            p = packs_dir("kokoro", "voices", v[0] + ".bin")
            if os.path.exists(p):
                out[stem] = {"lang": v[1], "name": display_name(stem), "path": p}
    return out


def languages():
    """Every language with a downloadable voice."""
    return sorted({v[0] for v in CATALOG.values()})


def catalog(lang):
    """Every voice for a language, installed or downloadable, hand-picked ones first:
    [(stem, name, desc, installed)]"""
    have = installed()
    stems = sorted({s for s, v in CATALOG.items() if v[0] == lang} | {s for s in have if s[:2] == lang},
                   key=lambda s: (s not in NAMES, is_kokoro(s), s))     # (Kokoro's after the hand-picked)
    return [(s, display_name(s), describe(s), s in have) for s in stems]


def recommended(lang):
    """The voice to fetch when a language has none yet (a Piper one: quick on any computer)."""
    stems = [c[0] for c in catalog(lang) if not is_kokoro(c[0])]
    return stems[0] if stems else None


def remove(stem):
    """Delete a downloaded voice (never a bundled one); the Kokoro model goes with the last
    Kokoro voice."""
    from .packs import packs_dir
    if bundled(stem):
        return
    if is_kokoro(stem):
        p = packs_dir("kokoro", "voices", kokoro.VOICES[stem][0] + ".bin")
        if os.path.exists(p):
            os.remove(p)
        if not glob.glob(packs_dir("kokoro", "voices", "*.bin")) and kokoro_model():
            os.remove(kokoro_model())
        return
    for ext in (".onnx", ".ort", ".onnx.json"):
        p = packs_dir("voices", stem + ext)
        if os.path.exists(p):
            os.remove(p)


def for_language(lang):
    return {k: v for k, v in installed().items() if v["lang"] == lang}


def default_for(lang):
    vs = for_language(lang)
    if lang == "en" and DEFAULT_ENGLISH in vs:
        return DEFAULT_ENGLISH
    return next(iter(vs), None)
