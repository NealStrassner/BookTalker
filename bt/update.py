"""Updates: asks BookTalker's GitHub page for a newer release - only when the reader clicks
'Check for updates' (BookTalker never goes online by itself) - and runs its installer."""
import json
import os
import re
import tempfile
import urllib.request

from .packs import REPO, _ssl

API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"


def version_tuple(text):
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:4])


def latest():
    """The newest published release that carries an installer -> (version, installer url, bytes),
    or None. (Model downloads live in releases of their own, without an installer.)"""
    req = urllib.request.Request(API, headers={"User-Agent": "BookTalker", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, context=_ssl(), timeout=20) as r:
        releases = json.load(r)
    best = None
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        version = (rel.get("tag_name") or "").lstrip("vV")
        for a in rel.get("assets", []):
            name = a.get("name", "").lower()
            if name.startswith("booktalker-setup") and name.endswith(".exe") and version_tuple(version):
                if best is None or version_tuple(version) > version_tuple(best[0]):
                    best = (version, a["browser_download_url"], a.get("size", 0))
    return best


def is_newer(remote, local):
    return version_tuple(remote) > version_tuple(local)


def installer_path(version):
    return os.path.join(tempfile.gettempdir(), f"BookTalker-Setup-{version}.exe")


def run_installer(path):
    """Start the downloaded installer (Windows asks for permission when it installs for everyone)."""
    os.startfile(path)
