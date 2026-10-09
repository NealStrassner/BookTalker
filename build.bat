@echo off
rem Builds dist\BookTalker\BookTalker.exe (about 8 minutes).
cd /d "%~dp0"
.venv\Scripts\python.exe art\make_art.py
.venv\Scripts\pyinstaller.exe --noconfirm --distpath dist --workpath build BookTalker.spec
