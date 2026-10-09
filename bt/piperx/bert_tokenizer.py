"""The part of Hugging Face 'transformers' that Piper's Chinese voices use: BERT's WordPiece
tokenizer for bert-base-chinese (lower-case, every Chinese character its own token). Lets the
'pinyin' voices speak without that large library. Its word list (vocab.txt, Apache-2.0, Google)
downloads with the voice, next to the g2pW model."""
import unicodedata

VOCAB_FILE = "bert-vocab.txt"


def _is_cjk(cp):
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF or
            0x2A700 <= cp <= 0x2B73F or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF or
            0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


def _is_punct(ch):
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


class BertTokenizer:
    """tokenize() and convert_tokens_to_ids(), as transformers.BertTokenizer does them for
    bert-base-chinese (do_lower_case=True)."""

    def __init__(self, vocab_path):
        with open(vocab_path, encoding="utf-8") as f:
            self.vocab = {line.rstrip("\n"): i for i, line in enumerate(f)}
        self.unk = "[UNK]"

    @classmethod
    def from_pretrained(cls, _source):
        import os
        from ..packs import packs_dir
        return cls(os.path.join(packs_dir("g2pW"), VOCAB_FILE))

    def _basic(self, text):
        out, word = [], []

        def flush():
            if word:
                out.append("".join(word))
                word.clear()
        text = unicodedata.normalize("NFD", text.lower())
        for ch in text:
            cp = ord(ch)
            if cp == 0 or cp == 0xFFFD or (unicodedata.category(ch).startswith("C") and ch not in "\t\n\r"):
                continue
            if unicodedata.category(ch) == "Mn":           # accents are stripped
                continue
            if ch.isspace():
                flush()
            elif _is_cjk(cp) or _is_punct(ch):
                flush()
                out.append(ch)
            else:
                word.append(ch)
        flush()
        return out

    def _wordpiece(self, word):
        if len(word) > 100:
            return [self.unk]
        pieces, start = [], 0
        while start < len(word):
            end, cur = len(word), None
            while start < end:
                sub = ("##" if start else "") + word[start:end]
                if sub in self.vocab:
                    cur = sub
                    break
                end -= 1
            if cur is None:
                return [self.unk]
            pieces.append(cur)
            start = end
        return pieces

    def tokenize(self, text):
        return [p for w in self._basic(text) for p in self._wordpiece(w)]

    def convert_tokens_to_ids(self, tokens):
        unk = self.vocab.get(self.unk, 100)
        return [self.vocab.get(t, unk) for t in tokens]
