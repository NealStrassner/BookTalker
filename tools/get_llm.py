"""One-time: fetch the llama.cpp engine (Vulkan + CPU builds) and the Qwen translator model.

    .venv\\Scripts\\python.exe tools\\get_llm.py
"""
import io
import os
import ssl
import urllib.request
import zipfile

import certifi
from huggingface_hub import hf_hub_download

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LLAMA_TAG = "b11404"
MODEL_REPO = "bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF"
MODEL_FILE = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"

ctx = ssl.create_default_context(cafile=certifi.where())
ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
for kind in ("vulkan", "cpu"):
    dest = os.path.join(ROOT, "engines", "llama", kind)
    if os.path.exists(os.path.join(dest, "llama-server.exe")):
        continue
    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/llama-{LLAMA_TAG}-bin-win-{kind}-x64.zip"
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "BookTalker"}), context=ctx).read()
    z = zipfile.ZipFile(io.BytesIO(data))
    os.makedirs(dest, exist_ok=True)
    for name in z.namelist():   # only the server and the libraries it needs
        base = os.path.basename(name)
        if base and (base == "llama-server.exe" or base.lower().endswith(".dll")):
            with open(os.path.join(dest, base), "wb") as f:
                f.write(z.read(name))
    print(kind, "ok", sorted(os.listdir(dest)))
path = hf_hub_download(MODEL_REPO, MODEL_FILE, local_dir=os.path.join(ROOT, "models", "qwen"))
print("model", path, f"{os.path.getsize(path) / 1e9:.2f} GB")
