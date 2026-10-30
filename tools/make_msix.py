"""Pack dist\\BookTalker into release\\BookTalker-<version>.msix for the Microsoft Store (which
signs it). The package's folder is build\\msix: the program (linked, not copied), the logos,
their index (resources.pri) and store\\AppxManifest.xml with the version filled in.

    .venv\\Scripts\\python.exe tools\\make_msix.py

makeappx and makepri come from Microsoft's Microsoft.Windows.SDK.BuildTools package (nuget.org),
unpacked into build\\sdktools\\pkg.
(For a test on a PC in Developer Mode, register the folder itself:
 Add-AppxPackage -Register build\\msix\\AppxManifest.xml)
"""
import ast
import glob
import os
import shutil
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = sorted(glob.glob(os.path.join(ROOT, "build", "sdktools", "pkg", "bin", "*", "x64")))[-1]
# Start menu and Store tiles: (name, width, height, logo size) at scale 100; scale 200 is double
TILES = [("StoreLogo", 50, 50, 50), ("Square44x44Logo", 44, 44, 44),
         ("Square150x150Logo", 150, 150, 120), ("Wide310x150Logo", 310, 150, 120)]
# the taskbar and lists: BookTalker's own icon frames, drawn without Windows' colored plate
ICON_SIZES = (16, 24, 32, 48, 256)


def main():
    with open(os.path.join(ROOT, "bt", "ui", "about.py"), encoding="utf-8") as f:
        version = next(node.value.value for node in ast.parse(f.read()).body
                       if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "VERSION")
    src = os.path.join(ROOT, "dist", "BookTalker")
    layout = os.path.join(ROOT, "build", "msix")
    shutil.rmtree(layout, ignore_errors=True)
    for root, _, files in os.walk(src):
        dest = os.path.join(layout, os.path.relpath(root, src))
        os.makedirs(dest, exist_ok=True)
        for name in files:
            os.link(os.path.join(root, name), os.path.join(dest, name))

    # the logos and the manifest go in a small folder of their own too, which makepri indexes
    res = os.path.join(ROOT, "build", "msix-res")
    shutil.rmtree(res, ignore_errors=True)
    assets = os.path.join(res, "Assets")
    os.makedirs(assets)
    logo = Image.open(os.path.join(ROOT, "art", "logo_256.png")).convert("RGBA")
    for name, w, h, size in TILES:
        for scale in (100, 200):
            k = scale // 100
            tile = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
            tile.alpha_composite(logo.resize((size * k, size * k), Image.LANCZOS), ((w - size) * k // 2, (h - size) * k // 2))
            tile.save(os.path.join(assets, f"{name}.scale-{scale}.png"))
    ico = Image.open(os.path.join(ROOT, "booktalker.ico"))
    for size in ICON_SIZES:
        frame = ico.ico.getimage((size, size)).convert("RGBA")
        for form in ("", "_altform-unplated", "_altform-lightunplated"):
            frame.save(os.path.join(assets, f"Square44x44Logo.targetsize-{size}{form}.png"))

    with open(os.path.join(ROOT, "store", "AppxManifest.xml"), encoding="utf-8") as f:
        manifest = f.read().replace("{VERSION}", version)
    for folder in (res, layout):
        with open(os.path.join(folder, "AppxManifest.xml"), "w", encoding="utf-8") as f:
            f.write(manifest)

    makepri = os.path.join(TOOLS, "makepri.exe")
    config = os.path.join(ROOT, "build", "priconfig.xml")
    subprocess.run([makepri, "createconfig", "/cf", config, "/dq", "en-US", "/pv", "10.0.0", "/o"],
                   check=True, stdout=subprocess.DEVNULL)
    with open(config, encoding="utf-8") as f:     # one index for every scale (a single package, no bundle)
        text = f.read()
    with open(config, "w", encoding="utf-8") as f:
        f.write("\n".join(line for line in text.splitlines() if "autoResourcePackage" not in line))
    subprocess.run([makepri, "new", "/pr", res, "/cf", config, "/mn", os.path.join(res, "AppxManifest.xml"),
                    "/of", os.path.join(layout, "resources.pri"), "/o"], check=True, stdout=subprocess.DEVNULL)
    shutil.copytree(assets, os.path.join(layout, "Assets"))

    out = os.path.join(ROOT, "release", f"BookTalker-{version}.msix")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run([os.path.join(TOOLS, "makeappx.exe"), "pack", "/o", "/d", layout, "/p", out],
                   check=True, stdout=subprocess.DEVNULL)
    print(f"{out}: {os.path.getsize(out) / 1e6:.0f} MB")


if __name__ == "__main__":
    sys.exit(main())
