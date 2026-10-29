"""Updates: asks BookTalker's GitHub page for a newer release - only when the reader clicks
'Check for updates' (BookTalker never goes online by itself).

An installed BookTalker updates file by file. Each release carries the whole program as a zip
(booktalker-files-<version>.zip), and a zip's list holds every file's size and CRC. BookTalker
reads only that list (a byte range of the zip), compares it with its own files, downloads just
the files that differ (byte ranges again), checks each one's CRC, and copies them in once it
has closed. Releases also carry the full installer, for new installs."""
import ctypes
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
import zlib

from .packs import REPO, _ssl

API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6F2B1C9E-4D7A-4B3E-9A51-B00C7A1C0DE1}_is1"


def version_tuple(text):
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:4])


def latest():
    """The newest published release that carries the program -> {"version", "installer": (url,
    bytes) or None, "files": (url, bytes) or None}, or None. (Model downloads live in releases of
    their own, without either.)"""
    req = urllib.request.Request(API, headers={"User-Agent": "BookTalker", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, context=_ssl(), timeout=20) as r:
        releases = json.load(r)
    best = None
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        version = (rel.get("tag_name") or "").lstrip("vV")
        if not version_tuple(version):
            continue
        found = {"version": version, "installer": None, "files": None}
        for a in rel.get("assets", []):
            name = a.get("name", "").lower()
            kind = ("installer" if name.startswith("booktalker-setup") and name.endswith(".exe") else
                    "files" if name.startswith("booktalker-files") and name.endswith(".zip") else None)
            if kind:
                found[kind] = (a["browser_download_url"], a.get("size", 0))
        if (found["installer"] or found["files"]) and (best is None or version_tuple(version) > version_tuple(best["version"])):
            best = found
    return best


def is_newer(remote, local):
    return version_tuple(remote) > version_tuple(local)


def program_dir():
    """The installed program's folder, or None for a development copy (which git updates)."""
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None


def work_dir(*parts):
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "BookTalker", "update", *parts)


class RemoteFile:
    """A file on the web, read like a file on disk a block at a time (HTTP byte ranges), so that
    zipfile can read a zip's list and single files out of it without the rest."""
    BLOCK = 1 << 20

    def __init__(self, url, size):
        self.url, self.size, self.pos = url, size, 0
        self.blocks = {}
        self.fetched = 0
        self.ctx = _ssl()

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0 or n > self.size - self.pos:
            n = max(0, self.size - self.pos)
        out = bytearray()
        while len(out) < n:
            index, offset = divmod(self.pos, self.BLOCK)
            piece = self._block(index)[offset:offset + n - len(out)]
            out += piece
            self.pos += len(piece)
        return bytes(out)

    def _block(self, index):
        if index not in self.blocks:
            first = index * self.BLOCK
            last = min(self.size, first + self.BLOCK) - 1
            req = urllib.request.Request(self.url, headers={"User-Agent": "BookTalker", "Range": f"bytes={first}-{last}"})
            with urllib.request.urlopen(req, context=self.ctx, timeout=60) as r:
                data = r.read()
            if len(data) != last - first + 1:
                raise OSError("the download was cut short")
            if len(self.blocks) >= 4:            # (reads run front to back: a few blocks are plenty)
                self.blocks.pop(next(iter(self.blocks)))
            self.blocks[index] = data
            self.fetched += len(data)
        return self.blocks[index]


def _crc(path):
    crc = 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            crc = zlib.crc32(chunk, crc)
    return crc


def plan(files, folder):
    """Compare the release's file list with the program in folder -> (zip, files that differ,
    files the release no longer has). Only the zip's list is downloaded here."""
    url, size = files
    z = zipfile.ZipFile(RemoteFile(url, size))
    changed, names = [], set()
    for info in z.infolist():
        if info.is_dir():
            continue
        rel = os.path.normpath(info.filename)
        if os.path.isabs(rel) or rel.startswith(".."):
            raise ValueError(f"unexpected file in the update: {info.filename}")
        names.add(os.path.normcase(rel))
        local = os.path.join(folder, rel)
        if not (os.path.isfile(local) and os.path.getsize(local) == info.file_size and _crc(local) == info.CRC):
            changed.append(info)
    gone = []
    for root, _, found in os.walk(os.path.join(folder, "_internal")):
        for name in found:
            rel = os.path.relpath(os.path.join(root, name), folder)
            if os.path.normcase(rel) not in names:
                gone.append(rel)
    return z, changed, gone


def fetch(z, changed, on_progress):
    """Download the files that differ into the update folder. zipfile checks each file's CRC as it
    reads it, and a file that does not match stops the update."""
    target = work_dir("files")
    shutil.rmtree(target, ignore_errors=True)
    total = sum(i.compress_size for i in changed) or 1
    start = _fetched(z)
    for info in changed:
        dest = os.path.join(target, os.path.normpath(info.filename))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(info) as src, open(dest, "wb") as f:
            while chunk := src.read(1 << 20):
                f.write(chunk)
                on_progress(min(1.0, (_fetched(z) - start) / total))
        if os.path.getsize(dest) != info.file_size:
            raise OSError(f"{info.filename} did not download whole")
    return target


def _fetched(z):
    remote = getattr(z.fp, "_file", z.fp)       # (zipfile wraps the file it was given)
    return getattr(remote, "fetched", 0)


def _uninstall_entry():
    """Where Windows lists this installation (for its version number), as reg.exe names it."""
    import winreg
    for hive, name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        try:
            winreg.CloseKey(winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY))
            return f"{name}\\{UNINSTALL_KEY}"
        except OSError:
            pass
    return None


def _writable(folder):
    probe = os.path.join(folder, ".booktalker-write-test")
    try:
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def install(version, folder, gone):
    """Hand the checked files to Windows' own copier (robocopy), which waits for BookTalker to
    close, copies them in, removes files the new version no longer has, and starts BookTalker
    again. Asks for administrator permission only when the program folder needs it. -> True if
    it started (False: the reader said no)."""
    files = work_dir("files")
    with open(work_dir("remove.txt"), "w", encoding="utf-8") as f:
        f.write("".join(rel + "\n" for rel in gone))
    with open(work_dir("pending.json"), "w", encoding="utf-8") as f:
        json.dump({"version": version}, f)
    exe = os.path.join(folder, "BookTalker.exe")
    entry = _uninstall_entry()
    # robocopy retries a file still in use once a second while BookTalker closes; exit codes of 8
    # and up mean a file could not be copied (then the old version starts and says so)
    line = (f'ping -n 3 127.0.0.1 >nul & '
            f'robocopy "{files}" "{folder}" /E /IS /IT /R:60 /W:1 /NP /NJH /NJS >nul & '
            + (f'(if not errorlevel 8 reg add "{entry}" /v DisplayVersion /d {version} /f /reg:64 >nul) & ' if entry else "")
            + f'(for /f "usebackq delims=" %f in ("{work_dir("remove.txt")}") do @del /f /q "{folder}\\%f" 2>nul) & '
            f'start "" explorer.exe "{exe}"')
    verb = "open" if _writable(folder) else "runas"
    ctypes.windll.ole32.CoInitializeEx(None, 0x2 | 0x4)    # (ShellExecute from a background thread)
    return ctypes.windll.shell32.ShellExecuteW(None, verb, "cmd.exe", f"/c {line}", None, 0) > 32


def finished(current):
    """After an update: -> ("done", version), ("failed", version) or None, and tidies up."""
    try:
        with open(work_dir("pending.json"), encoding="utf-8") as f:
            version = json.load(f)["version"]
    except (OSError, ValueError, KeyError):
        return None
    shutil.rmtree(work_dir(), ignore_errors=True)
    return ("done" if version_tuple(current) >= version_tuple(version) else "failed"), version


def installer_path(version):
    return work_dir(f"BookTalker-Setup-{version}.exe")


def run_installer(path):
    """Start a downloaded installer (Windows asks for permission when it installs for everyone)."""
    os.startfile(path)
