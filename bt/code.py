"""Computer code in books, and source files opened as books.

Code is found on a page by its typewriter (monospaced) font and by how its lines look
(semicolons, braces, 'def', 'x = y' ...). Then, as the reader chooses, it is
    explained   in plain English, a few lines at a time (the local AI when it is running on
                the graphics card, else our own rules); the code is highlighted meanwhile
    read        exactly as written, symbols by name: 'open paren', 'equals', 'semicolon'
    skipped
"""
import re
import unicodedata

MODES = ("explain", "verbatim", "skip")
MONO_FONT = re.compile(r"mono|courier|consol|menlo|monaco|typewriter|inconsolata|fira ?code|source ?code|"
                       r"cmtt|sfmono|andale|lucida ?console|lucida ?sans ?typewriter|ocr-?a|letter ?gothic|"
                       r"^tt|\btt\d|nimbusmon|freemono|cousine|hack\b|jetbrains|ubuntu ?mono|roboto ?mono", re.I)
CHUNK_LINES = 12          # explained a few lines at a time, so the highlight follows along

# (keywords count only with code around them: 'Long ago', 'into the valley' are prose)
STRONG = re.compile(
    r"^((async\s+)?def\s+\w+\s*\(|class\s+\w+\s*(\(.*\))?\s*[:{]|import\s+[\w.]+(\s+as\s+\w+)?;?$|"
    r"from\s+[.\w]+\s+import\s|#\s*(include|define|ifn?def|endif|pragma)\b|"
    r"(public|private|protected|static|final)\s+[\w<>\[\]]+\s+\w|(var|let|const|auto)\s+\w+\s*=|"
    r"(export\s+)?function\s*\w*\s*\(|(func|fn|pub fn)\s+\w+\s*\(|(if|while|for|switch|catch)\s*\(.*\)\s*\{?$|"
    r"\}?\s*else\s*(if\b.*)?\{$|(else|try|finally)\s*:$|except\b.*:$|elif\s.*:$|for\s+\w+(\s*,\s*\w+)*\s+in\s.*:$|"
    r"(int|void|char|float|double|bool|long|unsigned|size_t|string|String)\s+\**\w+\s*[(=;,\[]|"
    r"(echo|printf|println|puts)\s|(print|console\.log|System\.out\.\w+|printf)\s*\(|std::|"
    r"(SELECT|INSERT\s+INTO|DELETE\s+FROM|CREATE\s+TABLE|UPDATE\s+\w+\s+SET)\b|@\w+(\(.*\))?$|<\?php|"
    r"<!DOCTYPE|</?[a-z][\w-]*(\s[^>]*)?/?>|(using|package)\s+[\w.]+;|return\b.*;$|(break|continue);$|"
    r">>>\s|\.\.\.\s{3}|Traceback \(most recent call last\)|[A-Z]\w*(Error|Exception):\s|\$\s+[a-z][\w-]*(\s|$))")
WEAK = re.compile(r"^(return|if|while|for|with|elif|else|case|default|pass|break|continue|raise|yield|end|fi|done|"
                  r"then|do|begin|lambda|await|var|let|const|struct|enum|typedef|interface|module)\b")
CODE_BITS = re.compile(r"[;{}]\s*$|^\s*[{}]|==|!=|<=|>=|&&|\|\||\+=|-=|\*=|/=|->|=>|::|\+\+|--\s*;|"
                       r"\w\(\)|\w\([^()]*\)\s*[;:{]?\s*$|\[\w*\]|^\s*[\w.\[\]]+\s*=\s*\S|"
                       r"\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z]\w*\(|^\s*(#|//|/\*|\*/)")


# ---- finding code --------------------------------------------------------------------
def line_score(text):
    """How much one line looks like computer code: 1 sure, 0.5 maybe, 0 prose."""
    t = text.strip()
    if not t:
        return 0.0
    if STRONG.match(t):
        return 1.0
    bits = len(CODE_BITS.findall(t)) + (1 if WEAK.match(t) else 0)
    words = re.findall(r"[^\W\d_]+", t)
    if len(words) >= 6 and t.endswith((".", "?", "!", "\"", "”", ",", ";")) and bits <= 1:
        return 0.0                                   # a sentence of prose
    if bits >= 2:
        return 1.0
    return 0.5 if bits else 0.0


def block_score(lines):
    """Share of a block's lines that look like code (sure = 1, maybe = 0.5)."""
    lines = [l for l in lines if l.strip()]
    return sum(line_score(l) for l in lines) / len(lines) if lines else 0.0


def mono_words(page, words):
    """-> set of indexes of `words` (PyMuPDF word tuples) printed in a monospaced font."""
    try:
        d = page.get_text("rawdict", flags=0)
    except Exception:
        return set()
    spans, verdicts = [], {}            # font -> [equal-width spans, uneven spans]
    for b in d.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                chars = s.get("chars", [])
                if not any(c["c"].strip() for c in chars):
                    continue
                font = s.get("font", "")
                mono = bool(s.get("flags", 0) & 8) or bool(MONO_FONT.search(font))
                if not mono and len({c["c"] for c in chars if c["c"].isascii() and c["c"].isalpha()}) >= 3:
                    # fonts embedded without a name ('F53'): every letter equally wide = typewriter
                    # (3+ different Latin letters: digits are equally wide in most fonts, and so
                    # are Chinese and Japanese characters)
                    xs = [c["origin"][0] for c in chars]
                    steps = [b2 - a for a, b2 in zip(xs, xs[1:])]
                    even = bool(steps) and min(steps) > 0 and max(steps) <= 1.04 * min(steps)
                    verdicts.setdefault(font, [0, 0])[0 if even else 1] += 1
                spans.append((s["bbox"], mono, font))
    # a font is a typewriter font when every span of it that could be measured was even:
    # then its short spans ('>>>', '=', '105') count too
    even_fonts = {f for f, (yes, no) in verdicts.items() if yes and not no}
    spans = [(bb, mono or font in even_fonts) for bb, mono, font in spans]
    if not any(m for _b, m in spans):
        return set()
    out = set()
    for i, w in enumerate(words):
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        for (x0, y0, x1, y1), mono in spans:
            if x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5:
                if mono:
                    out.add(i)
                break
    # a page all in one typewriter font says nothing: the hidden OCR text of scans often is
    # (measured: every false find in 142 books), and so is a typed manuscript
    if len(out) >= 0.8 * len(words):
        return set()
    return out


def split_code(blocks, mono, all_code=False):
    """Layout blocks -> blocks with the code in them made their own 'Code' blocks.
    Words carry their index in the page's word list at w[6] // 100 (see layout.build_page).
    A run of lines becomes code when it is (mostly) in a typewriter font and looks like code,
    or, without a typewriter font (scans), when nearly every line is clearly code."""
    out = []
    for b in blocks:
        label = b["label"]
        if label not in ("Text", "ListGroup", "Code", "Caption", "Footnote"):
            out.append(b)
            continue
        if all_code:
            out.append(dict(b, label="Code"))
            continue
        lines = _lines(b["words"])
        texts = [" ".join(w[4] for w in ws) for ws in lines]
        is_mono = [sum(1 for w in ws if w[6] // 100 in mono) >= 0.6 * len(ws) for ws in lines]
        code = [False] * len(lines)
        if label == "Code":                     # the layout model says so: unless it is plainly prose
            if block_score(texts) >= 0.25 or sum(is_mono) >= 0.5 * len(lines):
                code = [True] * len(lines)
        else:
            i = 0
            while i < len(lines):               # runs of typewriter lines
                if not is_mono[i]:
                    i += 1
                    continue
                j = i
                while j < len(lines) and is_mono[j]:
                    j += 1
                run = texts[i:j]
                if (len(run) >= 2 and block_score(run) >= 0.35) or (len(run) == 1 and line_score(run[0]) >= 1.0
                                                                   and len(lines) > 1):
                    code[i:j] = [True] * (j - i)
                i = j
            if not any(is_mono) and len(lines) >= 3 and block_score(texts) >= 0.75 and \
                    sum(line_score(t) >= 1.0 for t in texts) >= 0.6 * len(texts):
                code = [True] * len(lines)      # a scan, or code set in an ordinary font
        if not any(code):
            out.append(b)
            continue
        cur, cur_code = [], None
        for ws, c in zip(lines, code):
            if cur and c != cur_code:
                out.append(_piece(b, cur, "Code" if cur_code else ("Text" if label == "Code" else label)))
                cur = []
            cur += ws
            cur_code = c
        out.append(_piece(b, cur, "Code" if cur_code else ("Text" if label == "Code" else label)))
    return out


def _lines(words):
    lines, last = [], None
    for w in words:
        if w[5] != last:
            lines.append([])
            last = w[5]
        lines[-1].append(w)
    return lines


def _piece(b, words, label):
    ys = [w[1] for w in words] + [w[3] for w in words]
    return {"label": label, "top": min(ys), "bottom": max(ys), "words": words}


def code_lines(raw):
    """raw words (page, x0, y0, x1, y1, text, line, n) of a code block -> [(line text with its
    indentation, [raw words])], spacing worked out from the typewriter grid."""
    lines, last = [], None
    for w in raw:
        if (w[0], w[6]) != last:
            lines.append([])
            last = (w[0], w[6])
        lines[-1].append(w)
    widths = [(w[3] - w[1]) / len(w[5]) for ws in lines for w in ws if len(w[5]) >= 3]
    cw = sorted(widths)[len(widths) // 2] if widths else 6.0
    left = {}
    for ws in lines:
        left[ws[0][0]] = min(left.get(ws[0][0], 1e9), ws[0][1])
    out = []
    for ws in lines:
        s = " " * max(0, round((ws[0][1] - left[ws[0][0]]) / cw))
        for k, w in enumerate(ws):
            if k:
                s += " " * max(1, round((w[1] - ws[k - 1][3]) / cw))
            s += w[5]
        out.append((s, ws))
    return out


def chunks(lines):
    """Code lines -> pieces of about CHUNK_LINES lines, cut where a statement starts at the
    outermost indentation (so a function or loop stays together when it fits)."""
    if not lines:
        return []
    ind = lambda s: len(s) - len(s.lstrip())
    base = min(ind(s) for s, _ in lines if s.strip()) if any(s.strip() for s, _ in lines) else 0
    python = guess_language("\n".join(s for s, _ in lines)) == "Python"
    out, cur = [], []
    doc = comment = False
    pending = ""
    for s, ws in lines:
        t = s.strip()
        whole = not (doc or comment or pending)        # never cut inside a docstring, comment or statement
        top = t and ind(s) <= base and not t.startswith(("}", ")", "]", "else", "elif", "except",
                                                         "finally", "catch", "end"))
        if cur and whole and (len(cur) >= CHUNK_LINES or (top and len(cur) >= CHUNK_LINES // 2)) \
                or len(cur) >= 3 * CHUNK_LINES:
            out.append(cur)
            cur = []
        cur.append((s, ws))
        if (t.count('"""') + t.count("'''")) % 2:
            doc = not doc
        elif not doc:
            if "/*" in t and "*/" not in t.split("/*")[-1]:
                comment = True
            elif comment and "*/" in t:
                comment = False
            elif not comment:
                stmt = (pending + " " + t).strip()
                pending = stmt if _open(stmt, python) and len(stmt) < 3000 else ""
    if cur:
        out.append(cur)
    return out


# ---- reading it exactly as written ---------------------------------------------------
SYMBOL = [(">>>", "prompt"), ("===", "triple equals"), ("!==", "not double equals"), ("**=", "power equals"), ("...", "dot dot dot"),
          ("<<=", "shift left equals"), (">>=", "shift right equals"),
          ("==", "double equals"), ("!=", "not equals"), ("<=", "less than or equal"), (">=", "greater than or equal"),
          ("=>", "arrow"), ("->", "arrow"), ("+=", "plus equals"), ("-=", "minus equals"), ("*=", "times equals"),
          ("/=", "divide equals"), ("%=", "mod equals"), ("&&", "and and"), ("||", "or or"), ("++", "plus plus"),
          ("--", "minus minus"), ("::", "double colon"), ("<<", "shift left"), (">>", "shift right"),
          ("**", "star star"), ("//", "slash slash"), ("/*", "start comment"), ("*/", "end comment"),
          ("=", "equals"), ("(", "open paren"), (")", "close paren"), ("[", "open bracket"), ("]", "close bracket"),
          ("{", "open brace"), ("}", "close brace"), ("<", "less than"), (">", "greater than"), (";", "semicolon"),
          (":", "colon"), (",", "comma"), (".", "dot"), ("+", "plus"), ("-", "minus"), ("*", "star"), ("/", "slash"),
          ("\\", "backslash"), ("%", "percent"), ("&", "ampersand"), ("|", "pipe"), ("^", "caret"), ("~", "tilde"),
          ("!", "exclamation mark"), ("?", "question mark"), ("#", "hash"), ("@", "at"), ("$", "dollar"),
          ('"', "quote"), ("'", "single quote"), ("`", "backtick"), ("_", "underscore"), ("“", "quote"),
          ("”", "quote"), ("‘", "single quote"), ("’", "single quote")]
TOKEN = re.compile(r"[^\W_]+|" + "|".join(re.escape(s) for s, _ in SYMBOL) + r"|\S")
SYMBOL_SAY = dict(SYMBOL)


def _ident(t):
    """'getElementById' -> 'get Element By Id', 'HTTPServer' -> 'HTTP Server'."""
    t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", t)
    return re.sub(r"(?<=[A-Za-z])(?=\d)", " ", t) if not t.isdigit() else t


def say_verbatim(token):
    """One printed token of code -> the words that read it out exactly."""
    parts = []
    for m in TOKEN.findall(token):
        if m in SYMBOL_SAY:
            parts.append(SYMBOL_SAY[m])
        elif m[0].isalnum():
            parts.append(_ident(m))
        else:
            parts.append(unicodedata.name(m, "symbol").lower())
    return " ".join(parts)


# ---- explaining it in plain English ------------------------------------------------------
def guess_language(code):
    c = code
    if re.search(r"^\s*(def |class \w+.*:\s*$|import \w|from [\w.]+ import|elif |print\(|>>> )", c, re.M) or \
            re.search(r":\s*$", c, re.M) and not re.search(r"[;{}]\s*$", c, re.M):
        return "Python"
    if re.search(r"^\s*#include|\bprintf\s*\(|\bint main\s*\(", c, re.M):
        return "C"
    if re.search(r"\bSystem\.out\.|\bpublic\s+(static\s+)?(void|class)\b", c):
        return "Java"
    if re.search(r"\bconsole\.log|\bfunction\s*\w*\s*\(|=>|\b(const|let)\s+\w+\s*=|document\.", c):
        return "JavaScript"
    if re.search(r"^\s*(SELECT|INSERT|UPDATE|CREATE TABLE|DELETE)\b", c, re.M | re.I):
        return "SQL"
    if re.search(r"<\?php|\$\w+\s*=", c):
        return "PHP"
    if re.search(r"^\s*(echo|fi|done|then)\b|^#!/bin/(ba)?sh", c, re.M):
        return "shell"
    if re.search(r"^\s*</?[a-z][\w-]*[ >]", c, re.M):
        return "HTML"
    if re.search(r"\bfn\s+\w+\s*\(|\blet\s+mut\b", c):
        return "Rust"
    if re.search(r"\bfunc\s+\w+\s*\(|:=", c):
        return "Go"
    if re.search(r"[;{}]\s*$", c, re.M):
        return "C-style"
    return ""


OPS = [("===", " is exactly "), ("!==", " is not exactly "), ("==", " equals "), ("!=", " is not "),
       ("<=", " is at most "), (">=", " is at least "), ("&&", " and "), ("||", " or "), ("->", " to "),
       ("=>", " gives "), ("**", " to the power "), ("//", " divided by "), ("<<", " shifted left by "),
       (">>", " shifted right by "), ("::", " "), ("<", " is less than "), (">", " is more than "),
       ("|", " together with "), ("&", " and also "), ("^", " either but not both "),
       ("+", " plus "), ("-", " minus "), ("*", " times "), ("/", " divided by "), ("%", " modulo "),
       ("!", " not "), ("=", " is ")]
WORDS = {"self": "it", "this": "it", "None": "nothing", "null": "nothing", "nil": "nothing", "NULL": "nothing",
         "True": "true", "False": "false", "int": "whole number", "char": "character", "double": "decimal number",
         "float": "decimal number", "bool": "true-or-false", "boolean": "true-or-false", "string": "text",
         "String": "text", "void": "nothing", "size_t": "size", "EOF": "the end of the input",
         "args": "arguments", "kwargs": "named arguments", "argv": "command-line arguments", "argc": "argument count",
         "elif": "otherwise if", "def": "define", "fn": "function",
         "func": "function", "var": "variable", "const": "constant", "dict": "dictionary",
         "init": "initialise", "__init__": "set up", "tmp": "temporary", "idx": "index", "num": "number",
         "cnt": "count", "msg": "message", "img": "image", "buf": "buffer", "cfg": "settings", "err": "error",
         "fd": "file", "fp": "file", "ptr": "pointer",
         "std": "standard", "cout": "the output", "cin": "the input", "endl": "a new line", "printf": "print"}
# names that read best as words when they are called: len(x) -> 'the length of x'
CALLS = {"len": "the length of", "str": "the text of", "int": "the whole number of", "float": "the decimal number of",
         "isinstance": "whether it is a kind of", "range": "the numbers in the range", "sorted": "the sorted",
         "sum": "the total of", "max": "the largest of", "min": "the smallest of", "abs": "the size of",
         "type": "the type of", "sizeof": "the size of", "strlen": "the length of", "malloc": "new memory for",
         "open": "the file", "input": "what the user types after", "list": "a list of", "dict": "a table of",
         "set": "a set of", "enumerate": "each numbered item of", "zip": "the pairs of", "round": "the rounded",
         "print": "print", "getchar": "the next character typed", "getch": "the next character typed"}
CHARS = {r"\n": "a new line", r"\t": "a tab", r"\0": "the end mark", " ": "a space", "": "an empty text",
         r"\\": "a backslash", r"\'": "a quote mark", r"\"": "a quote mark"}


def _strings(s):
    """Pull string literals out first ("..." / '...'), so their words are read as they are."""
    lits = []

    def keep(m):
        lit = m.group(0)[1:-1]
        if lit in CHARS:
            lits.append("\x01" + CHARS[lit])           # (said as words, not as a quotation)
            return f" \x00{len(lits) - 1}\x00 "
        lit = re.sub(r"%[-+0-9.]*l?[di]", " a number ", lit)          # printf-style blanks
        lit = re.sub(r"%[-+0-9.]*[fge]", " a decimal number ", lit)
        lit = re.sub(r"%[-+0-9.]*s|\{\w*(:[^}]*)?\}", " some text ", lit)
        lit = re.sub(r"\\[ntr]", " ", lit)
        lits.append(" ".join(lit.split()))
        return f" \x00{len(lits) - 1}\x00 "
    return re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`', keep, s), lits


def say_expr(s):
    """An expression in plain words: 'len(words) >= 15' -> 'the length of words is at least 15'."""
    s, lits = _strings(s.strip().rstrip(";"))
    empty = {"{}": "an empty collection", "[]": "an empty list", "()": "nothing", "''": "an empty text"}
    if s.replace(" ", "") in empty:
        return empty[s.replace(" ", "")]
    m = re.fullmatch(r"\s*([\[{(])(.*)([\]})])\s*", s)
    if m and len(_split_args(m.group(2))) >= 4:              # a long table or list: its size and first item
        items = [i for i in _split_args(m.group(2)) if i.strip()]
        restore = lambda x: re.sub(r"\x00(\d+)\x00", lambda k: _lit(lits[int(k.group(1))]), x)
        first = restore(items[0])
        if m.group(1) == "{" and ":" in first:
            k, v = first.split(":", 1)
            return f"a table of {len(items)} entries, the first linking {say_expr(k)} to {say_expr(v)}"
        return f"a list of {len(items)} items, starting with {say_expr(first)}"
    s = re.sub(r"\{\s*\}", " an empty collection ", s)
    s = re.sub(r"(?<![\w\])])\[\s*\]", " an empty list ", s)
    m = re.fullmatch(r"(.+?)\?(.+):(.+)", s)
    if m and "?" not in m.group(2) and not re.search(r"\w\?$", m.group(1).strip()):   # a ? b : c
        restore = lambda x: re.sub(r"\x00(\d+)\x00", lambda k: _lit(lits[int(k.group(1))]), x)
        return (f"{say_expr(restore(m.group(2)))} if {say_expr(restore(m.group(1)))}, "
                f"otherwise {say_expr(restore(m.group(3)))}")
    s = re.sub(r"\b(self|this)\s*\.\s*", "its ", s)
    s = re.sub(r"(\w)\s*->\s*(?=\w)", r"\1 ", s)                      # p->next -> 'p next'
    s = re.sub(r"(^|[\s(=,+\-/!<>&|])\*+\s*(?=[A-Za-z_(])", r"\1 the value at ", s)    # *p (C pointers)
    s = re.sub(r"(^|[\s(=,])&(?=[A-Za-z_])", r"\1 where to find ", s)                  # &x
    # calls: name(args) -> 'name of args'
    s = re.sub(r"([\w.]+)\s*\(\s*\)", lambda m: " " + CALLS.get(m.group(1), _name(m.group(1))) + " ", s)
    s = re.sub(r"([\w.]+)\s*\(", lambda m: " " + _call(m.group(1)) + " (", s)
    s = re.sub(r"(\w)\s*\[\s*([^\]]+)\]", r"\1 at \2", s)            # a[i] -> 'a at i'
    s = re.sub(r"\.(?=[A-Za-z_])", " ", s)                           # os.path.join -> os path join
    for op, word in OPS:
        s = s.replace(op, word)
    s = re.sub(r"[()\[\]{}]", " ", s)
    s = s.replace(",", " and ").replace(":", " ").replace(";", " ")
    out = []
    for t in s.split():
        if t.startswith("\x00"):
            lit = lits[int(t.strip("\x00"))]
            out.append(lit[1:] if lit.startswith("\x01") else f"“{lit}”" if lit.strip() else "an empty text")
        elif t in WORDS:
            out.append(WORDS[t])
        elif re.fullmatch(r"\w+", t):
            out.append(_name(t))
        else:
            out.append(t.strip("$@#&*\\^~|`"))
    text = " ".join(w for w in out if w)
    text = re.sub(r"\band(\s+and)+\b", "and", text)
    return re.sub(r"\s+", " ", text).strip()


def _lit(lit):
    """A pulled-out literal put back as code (for an expression that is said in parts)."""
    if lit.startswith("\x01"):
        return "'" + {v: k for k, v in CHARS.items()}.get(lit[1:], "") + "'"
    return '"' + lit + '"'


def _call(name):
    if name in CALLS:
        return CALLS[name]
    said = _name(name)
    return said if said.endswith(" of") else said + " of"


def _name(n):
    """A name in code -> words: 'max_retries' -> 'max retries', 'getUser' -> 'get user'."""
    n = n.strip(".")
    if n in WORDS:
        return WORDS[n]
    parts = [p for p in re.split(r"[._]+", n) if p]
    words = []
    for p in parts:
        words += [WORDS.get(w, w if w.isupper() and len(w) > 1 else w.lower()) for w in _ident(p).split()]
    return " ".join(words) or n


def _params(p):
    names = []
    for part in _split_args(p):
        part = part.strip()
        if not part or part in ("self", "cls", "this", "*", "/", "void"):
            continue
        default = None
        if "=" in part:
            part, default = part.split("=", 1)
        part = re.sub(r":.*$", "", part).strip()                      # Python type hint
        part = re.sub(r"\s*\[[^\]]*\]\s*$", "", part)                  # a C array: char line[]
        part = re.sub(r"^.*?[\s*&]+(?=\w+$)", "", part.strip())        # C/Java type before the name
        part = part.lstrip("*&")
        names.append(_name(part) + (f", which starts as {say_expr(default)}" if default else ""))
    return names


def _split_args(s):
    depth, cur, out = 0, "", []
    for c in s:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += c
    out.append(cur)
    return out


def _list(items):
    items = [i for i in items if i]
    if not items:
        return "nothing"
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


TYPES = {"int", "char", "float", "double", "long", "short", "void", "bool", "boolean", "size_t", "FILE", "unsigned",
         "signed", "string", "String", "byte", "auto", "var", "uint8_t", "int32_t", "int64_t", "uint32_t", "wchar_t"}
NOT_TYPES = {"return", "else", "new", "throw", "delete", "case", "goto", "print", "echo", "import", "from", "do",
             "yield", "await", "raise", "assert", "del", "global", "pass", "not", "and", "or", "in", "is"}


def _kind(typ, stars=0, arrays=(), func=False):
    """'char', 1 star -> 'a piece of text'; 'int', arrays ['10'] -> 'a list of 10 whole numbers'."""
    words = typ.split()
    base = " ".join(WORDS.get(w, _name(w)) for w in words if w not in ("const", "static", "extern", "register",
                                                                        "struct", "unsigned", "signed"))
    if "struct" in words:
        base += " record"
    if "unsigned" in words:
        base = "positive " + base
    if typ.endswith("char") and stars == 1 and not arrays:
        base, stars = "piece of text", 0
    elif typ.endswith("char") and arrays and not stars:
        return f"a piece of text{' up to ' + say_expr(arrays[0]) + ' characters long' if arrays[0] else ''}"
    desc = base
    for _ in range(stars):
        desc = "pointer to a " + desc
    if func:
        return f"a function giving back {('a ' + desc) if desc != 'nothing' else 'nothing'}"
    if arrays:
        n = arrays[0]
        return f"a list of {say_expr(n) + ' ' if n else ''}{desc}s"
    return ("an " if desc[:1] in "aeiou" else "a ") + desc


def _declare(typ, decls):
    """C declarations 'double sum, atof(char []);' -> 'Make sum, a decimal number, and atof, ...'."""
    parts, kinds = [], []
    for d in _split_args(decls):
        d = d.strip()
        init = None
        if "=" in d and "(" not in d.split("=")[0]:
            d, init = (x.strip() for x in d.split("=", 1))
        stars = len(d) - len(d.lstrip("*( "))
        stars = d[:stars].count("*")
        m = re.search(r"[A-Za-z_]\w*", d)
        if not m:
            return ""
        name, rest = m.group(0), d[m.end():]
        func = rest.lstrip(")").lstrip().startswith("(")
        arrays = re.findall(r"\[([^\]]*)\]", rest)
        kinds.append(_kind(typ, stars, arrays, func))
        part = f"{_name(name)}, {kinds[-1]}"
        if init:
            part += f", starting as {say_expr(init)}"
        parts.append((part, _name(name), init))
    if len(parts) > 1 and len(set(kinds)) == 1 and not any(i for _p, _n, i in parts):
        return f"Make {_list([n for _p, n, _i in parts])}, each {kinds[0]}."     # 'int n, sign;'
    return "Make " + "; ".join(p for p, _n, _i in parts) + "."


def explain_line(line, defn=False):
    """One line (statement) of code -> a plain-English sentence, or '' when there is nothing
    to say (a closing brace). defn: the line is followed by a block, so 'name(...)' defines it."""
    t = line.strip()
    t = re.sub(r"\s*\{\s*$", "", t).strip()               # an opening brace says nothing
    if not t or re.fullmatch(r"[{}()\[\];,]+|end|fi|done|esac|\*/|\"\"\"|'''", t):
        return ""
    m = re.match(r"^(#(?!include|define|!)|//+|--(?=\s)|/\*+|REM\b|')\s*(.*?)\s*(\*/)?$", t)
    if m:
        note = m.group(2).strip(" */")
        return f"A note: {note}." if re.search(r"[^\W\d_]{2}", note) else ""
    m = re.match(r"^@(\w[\w.]*)", t)
    if m:
        return f"It is marked as {_name(m.group(1))}."
    m = re.match(r"^\}\s*(\w+)\s*;$", t)                       # '} Treenode;' ends a typedef
    if m:
        return f"Call it {_name(m.group(1))}."
    m = re.match(r"^typedef\s+(struct|union|enum)\s+(\w+)\s*$", t)
    if m:
        return f"Define a {'record' if m.group(1) != 'enum' else 'list of choices'} called {_name(m.group(2))}:"
    m = re.match(r"^typedef\s+(.+?)\s*;$", t)
    if m:
        names = re.findall(r"[A-Za-z_]\w*", m.group(1))
        if len(names) >= 2:
            name = names[-1] if not re.search(r"\(\s*\*\s*\w+\s*\)", m.group(1)) else \
                re.search(r"\(\s*\*\s*(\w+)\s*\)", m.group(1)).group(1)
            typ = " ".join(n for n in names if n != name)
            what = "a pointer to a function" if "(*" in m.group(1).replace(" ", "") else _kind(typ, m.group(1).count("*"))
            return f"Let {_name(name)} be another name for {what}."
    m = re.match(r"^(?:(?:static|extern|const|inline|unsigned|signed|long|short|register)\s+)*"
                 r"((?:struct\s+)?[A-Za-z_]\w*)\s+([*\s]*[A-Za-z_]\w*\s*\([^()]*\))\s*;$", t)
    if m and m.group(1) not in NOT_TYPES:                    # a prototype: 'int getline(char s[], int lim);'
        typ = m.group(1)
        name = re.search(r"[A-Za-z_]\w*", m.group(2)).group(0)
        params = _params(m.group(2)[m.group(2).index("(") + 1:-1])
        gives = "" if typ == "void" else f", giving back {_kind(typ, m.group(2).count('*'))}"
        return f"Announce a function called {_name(name)}, which takes {_list(params)}{gives}."
    m = re.match(r"^((?:(?:static|extern|const|unsigned|signed|long|short|register|struct)\s+)*[A-Za-z_][\w<>]*)"
                 r"\s+([*(]*\s*[A-Za-z_][^=]*?(?:=.*)?);$", t)
    if m and m.group(1).split()[-1] not in NOT_TYPES and (m.group(1).split()[-1] in TYPES or m.group(1)[:1].isupper()
                                                           or "struct" in m.group(1)) and \
            not re.match(r"^[\w.]+\s*\(", m.group(2)):
        said = _declare(m.group(1), m.group(2))
        if said:
            return said
    m = re.match(r"^([A-Za-z_]\w*)\s*\(([^;]*)\)$", t)
    if m and defn and m.group(1) not in NOT_TYPES | {"if", "while", "for", "switch", "catch"}:
        return f"Define a function called {_name(m.group(1))}, which takes {_list(_params(m.group(2)))}."
    m = re.match(r"^(?:async\s+)?def\s+(\w+)\s*\((.*)\)\s*(?:->\s*([^:]+))?:?$", t)
    if m:
        name, params = m.group(1), _params(m.group(2))
        what = "set-up step" if name == "__init__" else f"function called {_name(name)}"
        return f"Define a {what}, which takes {_list(params)}."
    m = re.match(r"^(?:export\s+)?(?:async\s+)?function\s*\*?\s*(\w*)\s*\((.*)\)", t)
    if m:
        return f"Define a function called {_name(m.group(1)) or 'without a name'}, which takes {_list(_params(m.group(2)))}."
    m = re.match(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(?([^)=]*)\)?\s*=>\s*(.*?);?$", t)
    if m:
        body = m.group(3).strip()
        gives = f", and gives back {say_expr(body)}" if body and not body.startswith("{") else ""
        return f"Define a function called {_name(m.group(1))}, which takes {_list(_params(m.group(2)))}{gives}."
    m = re.match(r"^(?:pub\s+)?(?:fn|func)\s+(?:\([^)]*\)\s*)?(\w+)\s*\((.*?)\)", t)
    if m:
        return f"Define a function called {_name(m.group(1))}, which takes {_list(_params(m.group(2)))}."
    m = re.match(r"^(?:(?:public|private|protected|static|final|inline|virtual|extern|const|unsigned|signed|"
                 r"abstract|synchronized|override)\s+)*([\w<>\[\]:*&]+)\s+[*&]*(\w+)\s*\(([^;]*)\)\s*(const)?$", t)
    if m and m.group(1) not in ("return", "else", "new", "throw", "delete", "case", "goto"):
        typ, name, params = m.group(1), m.group(2), _params(m.group(3))
        gives = "" if typ == "void" else f" and gives back {_kind(typ.strip('*&'), typ.count('*'))}"
        return f"Define a function called {_name(name)}, which takes {_list(params)}{gives}."
    m = re.match(r"^(?:export\s+)?(?:public\s+|abstract\s+|final\s+)*(class|struct|interface|enum)\s+(\w+)"
                 r"\s*(?:\((.*)\)|extends\s+([\w.]+)|:\s*(?:public\s+)?([\w.]+))?", t)
    if m:
        kind, name = m.group(1), m.group(2)
        base = m.group(3) or m.group(4) or m.group(5)
        base = [b for b in _split_args(base or "") if b.strip() and b.strip() != "object"]
        word = {"class": "kind of thing", "struct": "record", "interface": "interface", "enum": "list of choices"}[kind]
        return f"Define a {word} called {_name(name)}" + (f", built on {_list([_name(b.strip()) for b in base])}." if base else ".")
    m = re.match(r"^from\s+([\w.]+)\s+import\s+(.+)$", t)
    if m:
        what = [_name(re.sub(r"\s+as\s+\w+", "", x).strip(" ()")) for x in m.group(2).split(",")]
        return f"Bring in {_list(what)} from {_name(m.group(1))}."
    m = re.match(r"^import\s+(.+?);?$", t)
    if m:
        what = m.group(1)
        mm = re.match(r"^\{?([^}]*)\}?\s+from\s+['\"](.+)['\"]$", what)
        if mm:
            return f"Bring in {_list([_name(x.strip()) for x in mm.group(1).split(',')])} from {mm.group(2)}."
        names = [_name(re.sub(r"\s+as\s+\w+", "", x).strip().strip("\"'")) for x in what.split(",")]
        return f"Bring in {_list(names)}."
    m = re.match(r"^#\s*include\s*[<\"]([^>\"]+)[>\"]", t)
    if m:
        lib = re.sub(r"\.h$", "", m.group(1))
        return f"Bring in the {lib} library."
    m = re.match(r"^#\s*define\s+(\w+)\s+(.*)$", t)
    if m:
        return f"Let {_name(m.group(1))} stand for {say_expr(m.group(2))}."
    m = re.match(r"^(?:using\s+namespace|using|package|namespace|use|mod)\s+([\w.:]+)", t)
    if m:
        return f"Use {_name(m.group(1).replace('::', '.'))}."
    m = re.match(r"^(?:\}\s*)?(elif\b|else\s+if\b|if\b)(.*)$", t)
    if m:
        cond, then = _head(m.group(2))
        start = "If" if m.group(1) == "if" else "Otherwise, if"
        if then:                                                       # if (x) return y;
            rest = explain_line(then)
            return f"{start} {say_expr(cond)}, {rest[:1].lower()}{rest[1:]}"
        return f"{start} {say_expr(cond)}:"
    if re.fullmatch(r"(?:\}\s*)?else\s*:?", t):
        return "Otherwise:"
    m = re.match(r"^for\s+(.+?)\s+in\s+(.+?):?$", t)
    if m:
        return f"For each {say_expr(m.group(1))} in {say_expr(m.group(2))}:"
    m = re.match(r"^for\s*\(\s*(?:const|let|var|auto)?\s*([\w\s,]+?)\s+(?:of|in|:)\s+(.+)\)$", t)
    if m:
        return f"For each {say_expr(m.group(1).split()[-1])} in {say_expr(m.group(2))}:"
    m = re.match(r"^for\s*\((.*);(.*);(.*)\)$", t)
    if m:
        init = re.match(r"^\s*(?:[\w<>]+\s+)?(\w+)\s*=\s*(.+?)\s*$", m.group(1))
        start = f"{_name(init.group(1))} at {say_expr(init.group(2))}" if init else say_expr(m.group(1))
        return (f"Repeat, starting with {start or 'nothing set'}, as long as "
                f"{say_expr(m.group(2)) or 'needed'}, and each time {_step(m.group(3))}:")
    m = re.match(r"^while\b(.*)$", t)
    if m:
        cond, _then = _head(m.group(1))
        return "Keep repeating forever:" if cond.strip() in ("True", "true", "1") else f"As long as {say_expr(cond)}, repeat:"
    if re.fullmatch(r"(?:\}\s*)?try\s*:?", t):
        return "Try the following:"
    m = re.match(r"^(?:\}\s*)?(?:except|catch)\s*\(?\s*([\w.]*)?(?:\s+(?:as\s+)?\w+)?\s*\)?\s*:?$", t)
    if m:
        return f"If that fails with {_name(m.group(1))}:" if m.group(1) else "If that fails:"
    if re.fullmatch(r"(?:\}\s*)?finally\s*:?", t):
        return "Whatever happens, finish with:"
    m = re.match(r"^with\s+(.+?)\s+as\s+(\w+)\s*:$", t)
    if m:
        return f"Using {say_expr(m.group(1))}, called {_name(m.group(2))}:"
    m = re.match(r"^(?:switch|match)\b(.*)$", t)
    if m:
        return f"Depending on {say_expr(_head(m.group(1))[0])}:"
    m = re.match(r"^case\s+(.*?)\s*:$", t)
    if m:
        return f"When it is {say_expr(m.group(1))}:"
    if re.fullmatch(r"default\s*:", t):
        return "In any other case:"
    m = re.match(r"^return\b\s*(.*?);?$", t)
    if m:
        return f"Give back {say_expr(m.group(1))}." if m.group(1) else "Stop here and go back."
    m = re.match(r"^yield\s+(.*)$", t)
    if m:
        return f"Hand out {say_expr(m.group(1))}."
    m = re.match(r"^(?:raise|throw)\s+(?:new\s+)?(.*?);?$", t)
    if m:
        return f"Stop with an error: {say_expr(m.group(1))}." if m.group(1) else "Pass the error on."
    if re.fullmatch(r"break;?", t):
        return "Leave the loop."
    if re.fullmatch(r"continue;?", t):
        return "Go on to the next round."
    if re.fullmatch(r"pass;?", t):
        return "Do nothing here."
    m = re.match(r"^(?:printf|println|print|puts|echo|console\.log|System\.out\.print(?:ln)?|"
                 r"std::cout\s*<<|cout\s*<<)\s*\(?(.*?)\)?;?$", t)
    if m:
        return f"Show {say_expr(m.group(1).replace('<<', ','))}."
    m = re.match(r"^(?:const|let|var|auto|final|static|global|nonlocal|my|local)?\s*"
                 r"(?:(?:unsigned\s+|long\s+|short\s+)*(?:int|char|float|double|bool|boolean|String|string|long|"
                 r"short|size_t|byte|auto|[A-Z]\w*(?:<[^>]*>)?)\s*[*&]?\s+)?(\**[\w.\[\]]+(?:\s*,\s*[\w.\[\]]+)*)"
                 r"\s*(?::\s*[\w\[\], ]+)?\s*(\+|-|\*|/|%|\|\||&&|\?\?)?=(?!=)\s*(.+?);?$", t)
    if m:
        target, op, value = m.group(1), m.group(2), m.group(3)
        names = _list([say_expr(x) for x in target.split(",")])
        if op == "+":
            return f"Add {say_expr(value)} to {names}."
        if op == "-":
            return f"Take {say_expr(value)} away from {names}."
        if op == "*":
            return f"Multiply {names} by {say_expr(value)}."
        if op == "/":
            return f"Divide {names} by {say_expr(value)}."
        return f"Set {names} to {say_expr(value)}."
    m = re.match(r"^([\w.\[\]]+)\s*(\+\+|--)\s*;?$|^(\+\+|--)\s*([\w.\[\]]+)\s*;?$", t)
    if m:
        name, op = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        return f"{'Add one to' if op == '++' else 'Take one from'} {say_expr(name)}."
    m = re.match(r"^(?:await\s+)?([\w.]+)\s*\((.*)\)\s*;?$", t)
    if m:
        args = [say_expr(a) for a in _split_args(m.group(2)) if a.strip()]
        return f"{_verb(m.group(1))}" + (f", with {_list(args)}." if args else ".")
    m = re.match(r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|WITH)\b", t, re.I)
    if m:
        return say_expr(t.replace("*", " everything ")).capitalize() + "."
    said = say_expr(t)
    return (said[0].upper() + said[1:] + ".") if re.search(r"[^\W\d_]", said) else ""


def _head(rest):
    """What follows 'if' / 'while' -> (condition, statement on the same line or '').
    'x > 1:' -> ('x > 1', ''); '(a > b) return 1;' -> ('a > b', 'return 1;')."""
    rest = re.sub(r"\s*(:|\bthen|\bdo)\s*$", "", rest.strip())
    if rest.startswith("("):
        depth = 0
        for i, c in enumerate(rest):
            depth += (c == "(") - (c == ")")
            if depth == 0:
                after = rest[i + 1:].strip()
                if not after:
                    return rest[1:i], ""
                if re.match(r"^(and|or|&&|\|\||[-+*/%<>=!&|^]|\.|\[)", after):
                    return rest, ""                 # '(a) and (b)': all one condition
                return rest[1:i], after
        return rest[1:], ""
    return rest, ""


def _step(s):
    s = s.strip()
    m = re.fullmatch(r"([\w.]+)\s*(\+\+|--)|(\+\+|--)\s*([\w.]+)", s)
    if m:
        name, op = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        return f"{'add one to' if op == '++' else 'take one from'} {_name(name)}"
    line = explain_line(s)
    return (line[0].lower() + line[1:]).rstrip(".") if line else say_expr(s)


def _verb(callee):
    """'os.makedirs' -> 'Run os make dirs', 'self.cache.save' -> 'Run its cache save'."""
    return "Run " + say_expr(callee)


def explain(code, python=None):
    """A piece of code -> plain-English sentences (our own rules: one per statement, with the
    code's own comments read as notes). A statement that runs over several lines (an open
    bracket, a backslash at the end) is explained once."""
    out, doc, pending, block = [], None, "", None
    if python is None:
        python = guess_language(code) == "Python"
    rows = code.split("\n")
    if any(r.lstrip().startswith(">>> ") for r in rows):     # a Python session: what is typed, what it answers
        typed = []
        for r in rows:
            t = r.strip()
            if t.startswith((">>> ", "... ")) or t in (">>>", "..."):
                typed.append(t[4:])
            elif t:
                if typed:
                    said = explain("\n".join(typed), python=True)
                    if said:
                        out.append(("Type: " if len(typed) == 1 else "") + said)
                    typed = []
                out.append(f"Python answers: {t}.")
        if typed:
            out.append(explain("\n".join(typed), python=True))
        return " ".join(x for x in out if x)
    for k, raw in enumerate(rows):
        t = raw.strip()
        if block is not None:                            # inside /* ... */: its words are a note
            end = "*/" in t
            block.append(t.split("*/")[0].strip(" *"))
            if end:
                note = " ".join(x for x in block if x)
                if re.search(r"[^\W\d_]{2}", note):
                    out.append(f"A note: {note.rstrip('.')}.")
                block = None
                t = t.split("*/", 1)[1].strip()
                if not t:
                    continue
            else:
                continue
        if not python and "/*" in t:
            s0, _ = _strings(t)
            if "/*" in s0:
                head, _, tail = t.partition("/*")
                if "*/" in tail:                         # a comment inside the line: said after it
                    note, _, after = tail.partition("*/")
                    t = (head + " " + after).strip()
                    rows[k] = t
                    if t:
                        nxt = next((r.strip() for r in rows[k + 1:] if r.strip()), "")
                        said = explain_line(t, defn=nxt.startswith("{"))
                        if said:
                            out.append(said)
                    if re.search(r"[^\W\d_]{2}", note):
                        out.append(f"A note: {note.strip(' *').rstrip('.')}.")
                    continue
                block = [tail.strip(" *")]
                t = head.strip()
                if not t:
                    continue
        if pending:                                      # carrying on an unfinished statement
            m = re.search(TAIL_COMMENT[python], t)
            t = pending + " " + (t[:m.start()].strip() if m else t)
            pending = ""
        if doc is None and _open(t, python) and len(t) < 3000:
            pending = t.rstrip("\\").rstrip()
            continue
        if doc is not None:                              # inside a docstring: its words are a note
            end = t.endswith(('"""', "'''"))
            doc.append(t.rstrip("\"'").strip())
            if end:
                note = " ".join(x for x in doc if x)
                if note:
                    out.append(f"A note: {note.rstrip('.')}.")
                doc = None
            continue
        if t.startswith(('"""', "'''")):
            body = t[3:]
            if body.endswith(('"""', "'''")) and len(body) >= 3:
                if body[:-3].strip():
                    out.append(f"A note: {body[:-3].strip().rstrip('.')}.")
            else:
                doc = [body]
            continue
        # a statement with a comment after it: the statement, then the comment
        code_part, comment = t, ""
        m = re.search(TAIL_COMMENT[python], t)
        if m and not re.search(r"[\"'][^\"']*$", t[:m.start()]):
            code_part, comment = t[:m.start()].strip(), m.group(2)
        nxt = next((r.strip() for r in rows[k + 1:] if r.strip()), "")
        s = explain_line(code_part, defn=not python and (nxt.startswith("{") or t.endswith("{")))
        if s:
            out.append(s)
        if comment and re.search(r"[^\W\d_]{2}", comment):
            out.append(f"A note: {comment.rstrip('.')}.")
    if pending:
        s = explain_line(pending)
        if s:
            out.append(s)
    return " ".join(out)


# a comment after a statement: '# ...' in Python ('//' divides there), '//' or '#' elsewhere
TAIL_COMMENT = {True: r"\s(#)\s*(.*)$", False: r"\s(//|#)\s*(.*)$"}


def _open(t, python):
    """True when this (partial) statement carries on onto the next line."""
    if t.endswith("\\"):
        return True
    if t.startswith(("#", "//", "/*", "*", '"""', "'''")):
        return False
    s, _ = _strings(t)
    s = re.sub(TAIL_COMMENT[python], "", s).rstrip()
    depth = s.count("(") + s.count("[") - s.count(")") - s.count("]")
    braces = s.count("{") - s.count("}")
    if not python:                    # in C, Java, JavaScript ... a brace at the end opens a block
        if s.endswith("{"):
            braces -= 1
        if s.lstrip().startswith("}"):
            braces += 1
    return depth > 0 or braces > 0


def intro(code, lines):
    """What the listener hears before a piece of code is explained."""
    lang = guess_language(code)
    what = f"a piece of {lang} code" if lang else "a piece of computer code"
    return f"Here is {what}, {lines} line{'s' if lines != 1 else ''} long."


AI_PROMPT = ("You explain computer code to someone listening to an audiobook who is not a programmer. "
             "In plain everyday {into}, say what this code does and why, in at most {n} short sentences. "
             "Speak it as flowing prose: no code, no symbols, no lists, no markdown, no names in quotes "
             "unless they matter. Reply with the explanation only.")


def explain_ai(engine, code, into="English", timeout=30):
    """The local AI's explanation (None when it can't give one in time)."""
    n = max(2, min(8, len([l for l in code.split("\n") if l.strip()]) // 2 + 1))
    msgs = [{"role": "system", "content": AI_PROMPT.format(into=into, n=n)},
            {"role": "user", "content": code}]
    try:
        text = engine.chat(msgs, max_tokens=60 * n, timeout=timeout)
    except Exception:
        return None
    text = re.sub(r"(?is)<think>.*?</think>", "", text or "")
    text = re.sub(r"[`*#>]+", "", text).strip()
    return " ".join(text.split()) or None


_said = {}                # (code, language) -> what was said, so going back repeats it exactly


def spoken_text(sentence, smart=None, lang="en", wait=10.0):
    """What the voice says for a piece of code, in `lang`: the local AI's explanation when it
    runs on the graphics card and answers within `wait` seconds, else our own rules (translated
    from English by the fast translator for other languages)."""
    key = (sentence.code, sentence.intro, lang)
    if key in _said:
        return _said[key]
    from .translate import LANGS, lang_name
    text = None
    engine = smart.engine if smart is not None and smart.best else None
    if engine is not None and engine.available():
        engine.start()                                   # (does nothing once started)
        if engine.ready.wait(timeout=wait) and engine.status == "gpu":
            text = explain_ai(engine, sentence.code, lang_name(lang), timeout=max(wait, 20))
    english = None
    if not text:
        english = explain(sentence.code)
    if sentence.intro:
        english = sentence.intro + " " + (english or "")
        if text:                                         # the AI's words follow the intro
            text = (_to(smart, sentence.intro, lang) if lang != "en" else sentence.intro) + " " + text
            english = None
    if english is not None:
        text = _to(smart, english, lang) if lang != "en" else english
    text = " ".join((text or "").split()) or "A piece of computer code."
    _said[key] = text
    return text


def _to(smart, english, lang):
    from .translate import LANGS
    if smart is None or lang not in LANGS:
        return english
    try:
        return smart.nllb.translate(english, "eng_Latn", LANGS[lang][0])
    except Exception:
        return english
