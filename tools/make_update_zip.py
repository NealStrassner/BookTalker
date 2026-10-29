"""Pack dist\\BookTalker into release\\booktalker-files-<version>.zip, the release file that
installed copies update from: BookTalker reads the zip's list of files (each with its size and
CRC) and downloads only the files that differ from its own.

    .venv\\Scripts\\python.exe tools\\make_update_zip.py
"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    import ast
    with open(os.path.join(ROOT, "bt", "ui", "about.py"), encoding="utf-8") as f:
        version = next(node.value.value for node in ast.parse(f.read()).body
                       if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "VERSION")
    src = os.path.join(ROOT, "dist", "BookTalker")
    out = os.path.join(ROOT, "release", f"booktalker-files-{version}.zip")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    count = 0
    with zipfile.ZipFile(out + ".part", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(src):
            for name in sorted(files):
                path = os.path.join(root, name)
                z.write(path, os.path.relpath(path, src).replace(os.sep, "/"))
                count += 1
    os.replace(out + ".part", out)
    print(f"{out}: {count} files, {os.path.getsize(out) / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
