# Third-party notices

BookTalker is made by Neal Strassner, Copyright © 2026, and is free software under the GNU Affero
General Public License v3 (see `LICENSE`). It is built on the work of many people. Each part below keeps its own licence; this file lists
them with the credit their licences ask for.

## Models and data inside the app

| Part | What it does | Licence | Source |
|---|---|---|---|
| NLLB-200 distilled 600M (converted to 8-bit CTranslate2) | the offline translator | **CC BY-NC 4.0 — non-commercial use only** | Meta AI, NLLB Team et al. (2022), https://huggingface.co/facebook/nllb-200-distilled-600M |
| Surya layout model (exported to ONNX, 8-bit) | finds the text, headings and pictures on a page | Datalab's modified AI Pubs Open RAIL-M: free for research, personal use and organisations under US$5M funding/revenue (listed as CC BY-NC-SA 4.0 on Hugging Face); passed on under the same terms | Datalab, https://github.com/datalab-to/surya |
| PaddleOCR PP-OCRv5/v6 recognition and detection models (ONNX, via RapidOCR) | reads scanned pages | Apache-2.0 | PaddlePaddle, https://github.com/PaddlePaddle/PaddleOCR ; RapidAI, https://github.com/RapidAI/RapidOCR |
| Tesseract `tessdata_fast` trained models (16 scripts + OSD) | reads Bengali, Hebrew, Georgian and other scanned scripts | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast |
| fastText `lid.176.ftz` | recognises the language of a book | CC BY-SA 3.0 | Facebook AI Research, https://fasttext.cc/docs/en/language-identification.html |
| wordfreq word lists | judges whether text reads as real words | CC BY-SA 4.0 (data from Google Books Ngrams, Leeds Internet Corpus, Wikipedia, OpenSubtitles and others; see the wordfreq README) | Robyn Speer, https://github.com/rspeer/wordfreq |
| Piper voice **en_GB-alba-medium** | the built-in English voice | recordings CC BY 4.0 | recordings: University of Edinburgh, Alba corpus, https://datashare.ed.ac.uk/handle/10283/3270 ; voice model: the Piper project, https://huggingface.co/rhasspy/piper-voices |
| espeak-ng data (inside piper-tts) | turns text into sounds for the voice | GPL-3.0-or-later | https://github.com/espeak-ng/espeak-ng |
| Lithuanian stress dictionary (`bt/piperx/lithuanian`) | where the Lithuanian voice puts the stress | CC BY 4.0 (built from the LIEPA corpus annotation, Vilnius University, and the g2p-lt-lexicon by Arūnas Smaliukas); letter-name and vocative lists GPL-3.0 | https://github.com/OHF-voice/piper1-gpl ; https://huggingface.co/datasets/meldynamics/liepa-tts ; https://github.com/svogunas/g2p-lt-lexicon ; build: https://github.com/RobertasTa/reginute |

**The translator is for non-commercial use.** BookTalker is given away free, which the NLLB licence
allows. The AGPL lets anyone reuse BookTalker's own code, even commercially, but whoever does that
must replace the NLLB model (and check the Surya model's terms) first.

## Downloaded only when the reader asks for them

| Part | Licence | Source |
|---|---|---|
| Other Piper voices (the voice picker shows each voice's licence; some are public domain, some CC BY, some non-commercial or research-only) | per voice | https://huggingface.co/rhasspy/piper-voices — each voice's `MODEL_CARD` |
| g2pW model and its lookup tables — how the Chinese voices Chaowen and Xiao Ya pronounce each character (fetched with those voices) | Apache-2.0 | Yi-Chang Chen, https://github.com/GitYCC/g2pW ; model file from the Piper project, https://huggingface.co/datasets/rhasspy/piper-checkpoints ; tables from the g2pW package, https://pypi.org/project/g2pw/ |
| BERT Chinese word list (`vocab.txt` of bert-base-chinese, fetched with the same voices) | Apache-2.0 | Google, https://huggingface.co/google-bert/bert-base-chinese |
| TLTK, its pronunciation part (`nlp.py` and seven dictionary files) — how the Thai voice pronounces (fetched with that voice; its licence file is kept beside it) | BSD-3-Clause | Wirote Aroonmanakun, Dept. of Linguistics, Chulalongkorn University, https://pypi.org/project/tltk/ |
| Qwen3-4B-Instruct-2507 (GGUF) — the optional AI translator | Apache-2.0 | Alibaba Qwen team, https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507 |
| llama.cpp (`llama-server`) — runs the AI translator | MIT | https://github.com/ggml-org/llama.cpp |

## Libraries with their own native code

| Library | Licence | Source |
|---|---|---|
| Qt 6 (through PySide6 / shiboken6) | LGPL-3.0 | https://www.qt.io , source at https://code.qt.io |
| MuPDF (through PyMuPDF) | AGPL-3.0 | Artifex, https://mupdf.com , https://github.com/ArtifexSoftware/mupdf |
| Tesseract OCR engine and Leptonica (through tesserocr) | Apache-2.0 / BSD-2-Clause | https://github.com/tesseract-ocr/tesseract , http://www.leptonica.org |
| cysignals (inside tesserocr) | LGPL-3.0 | https://github.com/sagemath/cysignals |
| LAME MP3 encoder (through lameenc) | LGPL-2.0-or-later | https://lame.sourceforge.io |
| ONNX Runtime | MIT | https://github.com/microsoft/onnxruntime |
| CTranslate2 | MIT | https://github.com/OpenNMT/CTranslate2 |
| OpenCV | Apache-2.0 | https://github.com/opencv/opencv |
| PortAudio (inside sounddevice) | MIT | http://www.portaudio.com |
| Python | PSF License | https://www.python.org |

The Qt and LAME libraries are separate files in the installed app and can be replaced; BookTalker's
complete source code is published, so the whole program can be rebuilt with changed versions of any
of these libraries.

## Code adapted into BookTalker

- `bt/piperx/phonemize_lithuanian.py`: taken unchanged (apart from its import lines) from piper1-gpl's
  main branch, https://github.com/OHF-voice/piper1-gpl , GPL-3.0-or-later.
- `bt/piperx/bert_tokenizer.py`: written for BookTalker to give the same tokens as Hugging Face
  transformers' `BertTokenizer` (Apache-2.0, https://github.com/huggingface/transformers) for
  bert-base-chinese.
- `bt/rar.py` (comic archives): the RAR 5 decoder and the RAR 3 filters follow libarchive's
  `archive_read_support_format_rar5.c` and `archive_read_support_format_rar.c`
  (https://github.com/libarchive/libarchive).

  > Copyright (c) 2003-2007 Tim Kientzle; Copyright (c) 2018 Grzegorz Antoniak; and the libarchive
  > contributors. All rights reserved.
  >
  > Redistribution and use in source and binary forms, with or without modification, are permitted
  > provided that the following conditions are met: 1. Redistributions of source code must retain the
  > above copyright notice, this list of conditions and the following disclaimer. 2. Redistributions
  > in binary form must reproduce the above copyright notice, this list of conditions and the
  > following disclaimer in the documentation and/or other materials provided with the distribution.
  >
  > THIS SOFTWARE IS PROVIDED BY THE AUTHOR(S) "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
  > INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
  > PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR(S) BE LIABLE FOR ANY DIRECT,
  > INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
  > PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
  > INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
  > LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
  > SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Python packages inside the app

Listed from the build itself (every package the installed program contains).

| Package | Version | Licence | Home |
|---|---|---|---|
| antlr4-python3-runtime | 4.9.3 | BSD-3-Clause | http://www.antlr.org |
| beautifulsoup4 | 4.15.0 | MIT | https://www.crummy.com/software/BeautifulSoup/bs4/download/ |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi/releases |
| charset-normalizer | 3.5.2 | MIT | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md |
| cobble | 0.1.4 | BSD-2-Clause | http://github.com/mwilliamson/python-cobble |
| colorama | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama |
| colorlog | 6.12.0 | MIT | https://github.com/borntyping/python-colorlog |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| ctranslate2 | 4.8.2 | MIT | https://opennmt.net |
| fast-langdetect | 1.0.1 | MIT |  |
| fasttext-predict | 0.9.2.4 | MIT License | https://github.com/searxng/fasttext-predict/ |
| ftfy | 6.3.1 | Apache-2.0 | https://github.com/rspeer/python-ftfy |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna/blob/master/HISTORY.md |
| lameenc | 1.8.4 | LGPL-3.0-or-later | https://github.com/chrisstaite/lameenc |
| langcodes | 3.5.1 | MIT | https://github.com/georgkrause/langcodes |
| locate | 1.1.1 | MIT | https://github.com/AutoActuary/locate |
| lxml | 6.1.3 | BSD-3-Clause | https://lxml.de/ |
| mammoth | 1.13.0 | BSD-2-Clause | https://github.com/mwilliamson/python-mammoth |
| ml_dtypes | 0.6.0 | Apache-2.0 | https://github.com/jax-ml/ml_dtypes |
| msgpack | 1.2.3 | Apache-2.0 | https://github.com/msgpack/msgpack-python/ |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://github.com/numpy/numpy |
| omegaconf | 2.3.1 | BSD-3-Clause | https://github.com/omry/omegaconf |
| onnx | 1.23.1 | Apache-2.0 | https://github.com/onnx/onnx |
| onnxruntime | 1.30.0 | MIT | https://onnxruntime.ai |
| opencv-python-headless | 5.0.0.93 | Apache-2.0 | https://github.com/opencv/opencv-python |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| pillow | 10.4.0 | HPND (MIT-CMU) | https://github.com/python-pillow/Pillow/blob/main/CHANGES.rst |
| piper-tts | 1.8.0 | GPL-3.0-or-later | http://github.com/OHF-voice/piper1-gpl |
| platformdirs | 4.12.3 | MIT | https://github.com/tox-dev/platformdirs |
| protobuf | 7.36.2 | BSD-3-Clause | https://developers.google.com/protocol-buffers/ |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| pyclipper | 1.4.0 | MIT | https://github.com/fonttools/pyclipper |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pymupdf | 1.28.2 | AGPL-3.0 (or Artifex commercial licence) | https://github.com/pymupdf/pymupdf |
| PySide6 | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Addons | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| PySide6_Essentials | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| python-pptx | 1.0.2 | MIT | https://github.com/scanny/python-pptx/blob/master/HISTORY.rst |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org/ |
| rapidocr | 3.9.2 | Apache-2.0 | https://rapidai.github.io/RapidOCRDocs |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python | https://github.com/mrabarnett/mrab-regex |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| robust-downloader | 0.0.2 | Apache-2.0 | https://github.com/fedebotu/robust-downloader |
| sentence-stream | 1.3.0 | Apache-2.0 | http://github.com/OHF-Voice/sentence-stream |
| sentencepiece | 0.2.2 | Apache-2.0 | https://github.com/google/sentencepiece |
| setuptools | 78.1.0 | MIT | https://github.com/pypa/setuptools |
| shapely | 2.1.2 | BSD-3-Clause | https://github.com/shapely/shapely |
| shiboken6 | 6.11.2 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | https://pyside.org |
| sounddevice | 0.5.6 | MIT | https://github.com/spatialaudio/python-sounddevice/ |
| soupsieve | 2.10 | MIT | https://github.com/facelessuser/soupsieve |
| tesserocr | 2.10.0 | MIT | https://github.com/sirfz/tesserocr |
| threadpoolctl | 3.7.0 | BSD-3-Clause | https://github.com/joblib/threadpoolctl |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | https://tqdm.github.io |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions/issues |
| unicode-rbnf | 2.4.1 | MIT | https://github.com/rhasspy/unicode-rbnf |
| urllib3 | 2.8.0 | MIT | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst |
| wcwidth | 0.9.2 | MIT | https://github.com/jquast/wcwidth |
| wordfreq | 3.1.1 | Apache-2.0 (code); data CC BY-SA 4.0, see below | https://github.com/rspeer/wordfreq/ |
| xlsxwriter | 3.2.9 | BSD-2-Clause | https://github.com/jmcnamara/XlsxWriter |
