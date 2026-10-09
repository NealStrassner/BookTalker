# BookTalker

BookTalker reads books aloud and lights up each word on the page as it is spoken, so you can
follow along. It is made for anyone who finds reading hard or tiring: children learning to read,
older readers, people with low vision or dyslexia, people learning a foreign language, and anyone
who would rather listen.

It runs entirely on your own computer. No account, no internet needed once installed, and your
books never leave your PC. It is free.

Made by Neal Strassner.

## What it does

- Opens PDFs, EPUB, MOBI/AZW3, FB2, Word, PowerPoint, OpenDocument, DjVu, CHM, comic books
  (CBZ/CBR), web pages, plain text, Markdown, scanned pages and photos of pages, and source code.
- Reads in a natural voice and highlights each word as it is heard. Click any word to read from there.
- Understands the page: skips headers, footers and page numbers, joins words broken across lines,
  follows text across columns and pages, reads comic panels and speech balloons in order (manga
  right to left).
- Reads scanned books with its own text recognition, in Latin, Cyrillic, Greek, Arabic, Hebrew,
  Chinese, Japanese, Korean, Hindi, Bengali, Tamil, Telugu, Thai, Georgian, Armenian and more.
- Translates as it reads: a book in one of about 120 languages can be heard in another.
- Chapters, search, bookmarks with notes, a sleep timer (minutes or "end of this chapter"),
  reading speed, and **Save as audiobook**: one MP3 per chapter in a folder named after the book.
- Computer code in a book can be explained in plain words or read out exactly.

## Install (Windows 10 and 11)

1. Download `BookTalker-Setup-<version>.exe` from the [Releases](../../releases) page.
2. Run it. It installs into Program Files for everyone on the PC; choose "only for me" if you
   have no administrator rights.
3. Windows may show "Windows protected your PC" (the installer is not code-signed): choose
   **More info → Run anyway**.

BookTalker comes with one English voice and its fast translator. On first start it offers more
voices and the optional **AI translator** (2.6 GB, best quality, needs a graphics card). Nothing is
downloaded unless you choose it, and you can add any of them later.

**Updates:** About → *Check for updates* looks for a newer version here and installs it, keeping
your books, bookmarks and voices. BookTalker only goes online when you ask it to: to download
something you chose (a voice, the AI translator) or to check for updates. Once downloaded,
everything, translation included, runs offline on your own computer.

## What computer it needs

| | Minimum | Comfortable |
|---|---|---|
| Memory (RAM) | 4 GB | 8 GB |
| Disk space | 1.5 GB | 2 GB, plus voices (about 60 MB each) and the AI translator (2.6 GB) |
| Processor | any 64-bit, 2 cores | 4 cores or more |
| Graphics card | not needed | 3 GB free video memory for the optional AI translator |

Measured: reading a book uses about 1 GB of memory. With the optional AI translator running on the
graphics card, about 2 GB. Without a suitable graphics card BookTalker uses its fast built-in
translator automatically.

## Voices

BookTalker uses [Piper](https://github.com/OHF-voice/piper1-gpl) voices. The built-in English voice
is **Alba**. The voice picker lists over 100 more in about 45 languages, downloaded only when you
choose them, straight from the Piper voice collection. Hover over a voice to see the licence of its
recordings.

## Licence

Copyright © 2026 Neal Strassner.

BookTalker is free software under the **GNU Affero General Public License v3** (`LICENSE`).

Some parts inside it have their own terms, listed in `THIRD_PARTY_NOTICES.md`. Two matter if you
want to reuse BookTalker:

- The built-in translator, **NLLB-200** by Meta AI, is licensed **for non-commercial use only**
  (CC BY-NC 4.0). Giving BookTalker away free is fine. Anyone who wants to sell a product built on
  BookTalker must replace it.
- The page-layout model, **Surya** by Datalab, is free for personal use, research, and
  organisations under US$5M revenue or funding (`licenses/SURYA_MODEL_LICENSE.txt`).

## Build from source

1. Install Python 3.12 and [uv](https://github.com/astral-sh/uv).
2. `uv venv .venv --python 3.12`, then `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`.
3. Download `build-models.zip` and `nllb-200-distilled-600M-int8.zip` from the `models-1` release.
   Unpack the first into this folder (it fills `models/` and `voices/`) and the second into
   `models\nllb-600m-int8\`.
4. Run `build.bat`. The program is written to `dist\BookTalker\`.
5. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php) and run
   `ISCC.exe installer\BookTalker.iss`. The installer is written to `installer\Output\`.
