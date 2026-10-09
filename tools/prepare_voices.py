"""One-time: turn each Piper voice into a fast-loading .ort file with the word-timing
(alignment) output already built in. The app then loads a voice in ~4 s instead of ~8 s
and needs no `onnx` package at runtime.

    .venv\\Scripts\\python.exe tools\\prepare_voices.py
"""
import glob
import os
import tempfile

import onnx
import onnxruntime as ort
from piper.patch_voice_with_alignment import add_alignment_output

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for src in sorted(glob.glob(os.path.join(ROOT, "voices", "*.onnx"))):
    out = src[:-5] + ".ort"
    if os.path.exists(out):
        continue
    model = onnx.load(src)
    add_alignment_output(model)
    with tempfile.TemporaryDirectory() as tmp:
        patched = os.path.join(tmp, "patched.onnx")
        onnx.save(model, patched)
        o = ort.SessionOptions()
        o.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC   # portable
        o.optimized_model_filepath = out
        o.add_session_config_entry("session.save_model_format", "ORT")
        ort.InferenceSession(patched, o, providers=["CPUExecutionProvider"])
    print(os.path.basename(out), f"{os.path.getsize(out) / 1e6:.0f} MB")
