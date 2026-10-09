"""Offline translation (NLLB-200, ~200 languages, int8 CTranslate2) + language detection."""
import re
from collections import Counter
import threading

from .paths import resource

CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]")
KANA = re.compile(r"[぀-ヿ]")
HANGUL = re.compile(r"[가-힯]")
# characters that exist only in one of the two Chinese scripts (common ones)
TRAD_ONLY = set("這們會說來時國對學發於與為裡個開關點東車馬長門問見話後還過進現電經書頭實認議歷龍體醫愛聽寫讀難")
SIMP_ONLY = set("这们会说来时国对学发于与为里个开关点东车马长门问见话后还过进现电经书头实认议历龙体医爱听写读难")

# ISO 639-1 (what the detector returns) -> NLLB code, display name
LANGS = {
    "en": ("eng_Latn", "English"), "zh": ("zho_Hans", "Chinese"), "fr": ("fra_Latn", "French"),
    "ru": ("rus_Cyrl", "Russian"), "es": ("spa_Latn", "Spanish"), "de": ("deu_Latn", "German"),
    "it": ("ita_Latn", "Italian"), "pt": ("por_Latn", "Portuguese"), "ja": ("jpn_Jpan", "Japanese"),
    "ko": ("kor_Hang", "Korean"), "ar": ("arb_Arab", "Arabic"), "hi": ("hin_Deva", "Hindi"),
    "nl": ("nld_Latn", "Dutch"), "pl": ("pol_Latn", "Polish"), "uk": ("ukr_Cyrl", "Ukrainian"),
    "tr": ("tur_Latn", "Turkish"), "vi": ("vie_Latn", "Vietnamese"), "th": ("tha_Thai", "Thai"),
    "id": ("ind_Latn", "Indonesian"), "ms": ("zsm_Latn", "Malay"), "fa": ("pes_Arab", "Persian"),
    "he": ("heb_Hebr", "Hebrew"), "el": ("ell_Grek", "Greek"), "sv": ("swe_Latn", "Swedish"),
    "no": ("nob_Latn", "Norwegian"), "nb": ("nob_Latn", "Norwegian"), "da": ("dan_Latn", "Danish"),
    "fi": ("fin_Latn", "Finnish"), "cs": ("ces_Latn", "Czech"), "sk": ("slk_Latn", "Slovak"),
    "hu": ("hun_Latn", "Hungarian"), "ro": ("ron_Latn", "Romanian"), "bg": ("bul_Cyrl", "Bulgarian"),
    "sr": ("srp_Cyrl", "Serbian"), "hr": ("hrv_Latn", "Croatian"), "ca": ("cat_Latn", "Catalan"),
    "la": ("ita_Latn", "Latin"), "bn": ("ben_Beng", "Bengali"), "ur": ("urd_Arab", "Urdu"),
    "ta": ("tam_Taml", "Tamil"), "sw": ("swh_Latn", "Swahili"), "tl": ("tgl_Latn", "Tagalog"),
    "cy": ("cym_Latn", "Welsh"), "eu": ("eus_Latn", "Basque"), "hy": ("hye_Armn", "Armenian"),
    "is": ("isl_Latn", "Icelandic"), "ka": ("kat_Geor", "Georgian"), "kk": ("kaz_Cyrl", "Kazakh"),
    "lb": ("ltz_Latn", "Luxembourgish"), "lt": ("lit_Latn", "Lithuanian"), "lv": ("lvs_Latn", "Latvian"),
    "ml": ("mal_Mlym", "Malayalam"), "ne": ("npi_Deva", "Nepali"), "sl": ("slv_Latn", "Slovenian"),
    "sq": ("als_Latn", "Albanian"), "te": ("tel_Telu", "Telugu"),
    # every other language the readers and the detector know, for the translator
    "af": ("afr_Latn", "Afrikaans"),
    "am": ("amh_Ethi", "Amharic"),
    "as": ("asm_Beng", "Assamese"),
    "ast": ("ast_Latn", "Asturian"),
    "az": ("azj_Latn", "Azerbaijani"),
    "ba": ("bak_Cyrl", "Bashkir"),
    "be": ("bel_Cyrl", "Belarusian"),
    "bo": ("bod_Tibt", "Tibetan"),
    "bs": ("bos_Latn", "Bosnian"),
    "ceb": ("ceb_Latn", "Cebuano"),
    "ckb": ("ckb_Arab", "Kurdish (Sorani)"),
    "eo": ("epo_Latn", "Esperanto"),
    "et": ("est_Latn", "Estonian"),
    "fo": ("fao_Latn", "Faroese"),
    "ga": ("gle_Latn", "Irish"),
    "gd": ("gla_Latn", "Scottish Gaelic"),
    "gl": ("glg_Latn", "Galician"),
    "gn": ("grn_Latn", "Guarani"),
    "gu": ("guj_Gujr", "Gujarati"),
    "ha": ("hau_Latn", "Hausa"),
    "ht": ("hat_Latn", "Haitian Creole"),
    "ig": ("ibo_Latn", "Igbo"),
    "ilo": ("ilo_Latn", "Ilocano"),
    "jv": ("jav_Latn", "Javanese"),
    "km": ("khm_Khmr", "Khmer"),
    "kn": ("kan_Knda", "Kannada"),
    "ku": ("kmr_Latn", "Kurdish (Kurmanji)"),
    "ky": ("kir_Cyrl", "Kyrgyz"),
    "lo": ("lao_Laoo", "Lao"),
    "mai": ("mai_Deva", "Maithili"),
    "mg": ("plt_Latn", "Malagasy"),
    "mk": ("mkd_Cyrl", "Macedonian"),
    "mn": ("khk_Cyrl", "Mongolian"),
    "mr": ("mar_Deva", "Marathi"),
    "mt": ("mlt_Latn", "Maltese"),
    "my": ("mya_Mymr", "Burmese"),
    "nn": ("nno_Latn", "Norwegian Nynorsk"),
    "ny": ("nya_Latn", "Chichewa"),
    "oc": ("oci_Latn", "Occitan"),
    "or": ("ory_Orya", "Odia"),
    "pa": ("pan_Guru", "Punjabi"),
    "pap": ("pap_Latn", "Papiamento"),
    "ps": ("pbt_Arab", "Pashto"),
    "qu": ("quy_Latn", "Quechua"),
    "rw": ("kin_Latn", "Kinyarwanda"),
    "sa": ("san_Deva", "Sanskrit"),
    "sd": ("snd_Arab", "Sindhi"),
    "si": ("sin_Sinh", "Sinhala"),
    "sn": ("sna_Latn", "Shona"),
    "so": ("som_Latn", "Somali"),
    "su": ("sun_Latn", "Sundanese"),
    "tg": ("tgk_Cyrl", "Tajik"),
    "tk": ("tuk_Latn", "Turkmen"),
    "tt": ("tat_Cyrl", "Tatar"),
    "ug": ("uig_Arab", "Uyghur"),
    "uz": ("uzn_Latn", "Uzbek"),
    "war": ("war_Latn", "Waray"),
    "xh": ("xho_Latn", "Xhosa"),
    "yi": ("ydd_Hebr", "Yiddish"),
    "yo": ("yor_Latn", "Yoruba"),
    "yue": ("yue_Hant", "Cantonese"),
    "zu": ("zul_Latn", "Zulu"),
    "arz": ("arz_Arab", "Egyptian Arabic"),
    "pnb": ("urd_Arab", "Western Punjabi"),   # (not in NLLB; Urdu is the nearest, same script)
    "bh": ("bho_Deva", "Bhojpuri"),
    "li": ("lim_Latn", "Limburgish"),
    "scn": ("scn_Latn", "Sicilian"),
    "vec": ("vec_Latn", "Venetian"),
    "sc": ("srd_Latn", "Sardinian"),
    "lmo": ("lmo_Latn", "Lombard"),
}
LATIN_SCRIPT = {c for c, v in LANGS.items() if v[0].endswith("_Latn")} | {"la", "eo"}   # languages written in Latin letters


def lang_name(code):
    return LANGS.get(code, (None, code.upper() if code else "Unknown"))[1]


def detect_language(text):
    """-> ISO 639-1 code for a sample of the book's text."""
    import unicodedata
    sample = unicodedata.normalize("NFKC", " ".join(text.split())[:3000])   # (shaped Arabic letters 'ﮐﺎ' -> 'کا')
    if not sample:
        return "en"
    han = len(CJK.findall(sample))
    if han > len(sample) * 0.2:
        if len(KANA.findall(sample)) > han * 0.05:
            return "ja"
        if len(HANGUL.findall(sample)) > han * 0.3:
            return "ko"
        return "zh"
    try:
        from fast_langdetect import detect
        first = lambda s: (lambda r: (r[0] if isinstance(r, list) else r)["lang"])(detect(s))
        lang = first(sample.replace("\n", " "))
        letters = [c for c in sample if c.isalpha()]
        latin = sum(c.isascii() for c in letters)
        if letters and latin < 0.4 * len(letters) and lang in LATIN_SCRIPT:
            # one English line ('estimated to be only 40% accurate') outweighed a page of rough
            # OCR'd Urdu: judge the page by its own script's words
            other = " ".join(w for w in sample.split() if not any(c.isascii() and c.isalpha() for c in w))
            if other:
                lang = first(other)
        return lang
    except Exception:
        return "en"


def detect_book_language(page_texts):
    """-> (language, text of the pages in it): one vote per page with real text, so a front page
    in another language (Google's English notice on a French scan) doesn't decide the book.
    Short pages (a children's book's line or two) are pooled, so a dozen story pages outvote
    the two long licence pages at the back."""
    votes, texts = Counter(), {}
    pages, pool = [], ""
    for t in page_texts:
        t = " ".join(t.split())
        if len(t) >= 100:
            pages.append(t)
        elif len(t) >= 8:
            pool += " " + t
            if len(pool) >= 150:
                pages.append(pool)
                pool = ""
    if len(pool) >= 60 or not pages:
        pages.append(pool or " ".join(page_texts))
    for t in pages:
        lang = detect_language(t)
        votes[lang] += 1
        texts.setdefault(lang, []).append(t)
    lang = max(votes, key=lambda l: (votes[l], sum(map(len, texts[l]))))
    return lang, " ".join(texts[lang])


def nllb_code(lang, sample=""):
    if lang == "zh":
        t = sum(c in TRAD_ONLY for c in sample)
        s = sum(c in SIMP_ONLY for c in sample)
        return "zho_Hant" if t > s else "zho_Hans"
    return LANGS.get(lang, ("eng_Latn",))[0]


CJK_ANY = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")   # written without spaces (Korean uses spaces)


def join_text(words):
    """Words -> text: no space next to CJK characters/punctuation, spaces elsewhere."""
    out = ""
    for w in words:
        if not w:
            continue
        if out and not (CJK_ANY.match(out[-1]) or CJK_ANY.match(w[0])):
            out += " "
        out += w
    return out


class Translator:
    """Loads on first use; thread-safe; caches every sentence it translates."""

    def __init__(self):
        self._tr = None
        self._sp = None
        self._lock = threading.Lock()
        self._cache = {}

    @staticmethod
    def available():
        """The fast translator is a download (packs.translator_items); False until it's there."""
        from .packs import translator_dir
        return translator_dir() is not None

    def _load(self):
        import ctranslate2
        import sentencepiece as spm
        from .packs import translator_dir
        d = translator_dir()
        if d is None:
            raise RuntimeError("the translator is not downloaded")
        self._tr = ctranslate2.Translator(d, device="cpu", compute_type="int8",
                                          inter_threads=1, intra_threads=4)
        self._sp = spm.SentencePieceProcessor(model_file=d + "/sentencepiece.bpe.model")

    def translate(self, text, src_code, tgt_code="eng_Latn"):
        key = (text, src_code, tgt_code)
        if key in self._cache:
            return self._cache[key]
        with self._lock:
            if self._tr is None:
                self._load()
            pieces = self._sp.encode(text, out_type=str)[:400]
            r = self._tr.translate_batch([[src_code] + pieces + ["</s>"]], target_prefix=[[tgt_code]],
                                         beam_size=4, max_decoding_length=320, repetition_penalty=1.15)
            out = self._sp.decode(r[0].hypotheses[0][1:]).strip()
        self._cache[key] = out
        return out

    def translate_many(self, texts, src_code, tgt_code="eng_Latn"):
        """Several short texts at once (chapter titles): one batch, much faster than one by one."""
        todo = [t for t in dict.fromkeys(texts) if (t, src_code, tgt_code) not in self._cache and t.strip()]
        if todo:
            with self._lock:
                if self._tr is None:
                    self._load()
                batch = [[src_code] + self._sp.encode(t, out_type=str)[:120] + ["</s>"] for t in todo]
                rs = self._tr.translate_batch(batch, target_prefix=[[tgt_code]] * len(batch), beam_size=2,
                                              max_decoding_length=160, repetition_penalty=1.15, max_batch_size=16)
                for t, r in zip(todo, rs):
                    self._cache[(t, src_code, tgt_code)] = self._sp.decode(r.hypotheses[0][1:]).strip()
        return [self._cache.get((t, src_code, tgt_code), t) for t in texts]
