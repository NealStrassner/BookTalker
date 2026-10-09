"""Piper voices: the ones on this computer, and every one BookTalker can download."""
import glob
import os

from .paths import resource
from .voice_catalog import CATALOG as _ALL, UNSUPPORTED

CATALOG = {k: v for k, v in _ALL.items() if k not in UNSUPPORTED}   # voices that can speak here

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
    """The licence of the voice's recordings ('public domain', 'CC BY 4.0', 'non-commercial' ...)."""
    from .voice_catalog import LICENSES
    return LICENSES.get(stem, "")


def size_mb(stem):
    return CATALOG[stem][3] if stem in CATALOG else None


def describe(stem):
    """e.g. 'Spanish (México) · man', in the interface language."""
    from .ui.i18n import lang_label, tr
    reg = region(stem)
    gender = NAMES.get(stem, ("", "", ""))[2]
    text = lang_label(stem[:2]) + (f" ({reg})" if reg else "")
    return text + (f" · {tr(gender)}" if gender else "")


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
    return out


def languages():
    """Every language with a downloadable voice."""
    return sorted({v[0] for v in CATALOG.values()})


def catalog(lang):
    """Every voice for a language, installed or downloadable, hand-picked ones first:
    [(stem, name, desc, installed)]"""
    have = installed()
    stems = sorted({s for s, v in CATALOG.items() if v[0] == lang} | {s for s in have if s[:2] == lang},
                   key=lambda s: (s not in NAMES, s))
    return [(s, display_name(s), describe(s), s in have) for s in stems]


def recommended(lang):
    """The voice to fetch when a language has none yet."""
    stems = [c[0] for c in catalog(lang)]
    return stems[0] if stems else None


def remove(stem):
    """Delete a downloaded voice (never a bundled one)."""
    from .packs import packs_dir
    if bundled(stem):
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
