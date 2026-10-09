"""One-time: export Surya's rf-detr page-layout model to ONNX (models/layout.onnx), so the
app runs it with onnxruntime and needs neither torch, torchvision, transformers nor surya.

    .venv\\Scripts\\python.exe tools\\export_layout_onnx.py
"""
import json
import os
import sys

import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tools", "source_models", "surya_layout2")
OUT = os.path.join(ROOT, "models", "layout.onnx")


class Wrapped(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, x):
        out = self.model(x)
        return out["pred_logits"], out["pred_boxes"]


_interp = torch.nn.functional.interpolate


def _interp_const(input, *a, **k):
    """DINOv2 resizes its learned position table with antialiased bicubic, which ONNX lacks.
    For a fixed input size the result never changes, so compute it outside the trace and
    let the exporter store it as a constant."""
    if k.get("antialias"):
        state = torch._C._get_tracing_state()
        torch._C._set_tracing_state(None)
        try:
            return _interp(input.detach().clone(), *a, **k)
        finally:
            torch._C._set_tracing_state(state)
    return _interp(input, *a, **k)


def _static_layernorm(self, x):
    """Same maths as surya's projector LayerNorm, with the size taken from the layer
    (static) instead of x.size(3) (dynamic), which the ONNX exporter can't handle."""
    x = x.permute(0, 2, 3, 1)
    x = torch.nn.functional.layer_norm(x, self.normalized_shape, self.weight, self.bias, self.eps)
    return x.permute(0, 3, 1, 2)


def main():
    torch.nn.functional.interpolate = _interp_const
    from surya.common.rfdetr.models.backbone import projector
    projector.LayerNorm.forward = _static_layernorm
    from surya.common.rfdetr_torch import RfDetrTorch
    det = RfDetrTorch(SRC, device="cpu")
    model = det.model.model.eval()
    res = det.model.resolution
    x = torch.randn(1, 3, res, res)
    with torch.inference_mode():
        ref = Wrapped(model)(x)
    torch.onnx.export(Wrapped(model), (x,), OUT, input_names=["image"],
                      output_names=["logits", "boxes"], opset_version=17,
                      do_constant_folding=True, dynamo=False)
    cfg = json.load(open(os.path.join(SRC, "config.json")))
    cats = sorted(cfg["categories"], key=lambda c: c["id"])
    meta = {"resolution": res, "num_select": det.model.num_select,
            "labels": [c["name"] for c in cats]}
    json.dump(meta, open(OUT[:-5] + ".json", "w"), indent=1)
    # parity check on the random input
    import numpy as np
    import onnxruntime as ort
    s = ort.InferenceSession(OUT, providers=["CPUExecutionProvider"])
    lo, bo = s.run(None, {"image": x.numpy()})
    print("max |logits diff|", float(np.abs(lo - ref[0].numpy()).max()),
          " max |boxes diff|", float(np.abs(bo - ref[1].numpy()).max()))
    print("saved", OUT, f"{os.path.getsize(OUT) / 1e6:.0f} MB")
    # 8-bit weights: 121 MB -> 34 MB; measured 544/555 sentences identical on 24 test pages
    from onnxruntime.quantization import QuantType, quantize_dynamic
    fp32 = os.path.join(ROOT, "tools", "source_models", "layout_fp32.onnx")
    os.replace(OUT, fp32)
    quantize_dynamic(fp32, OUT, weight_type=QuantType.QInt8)
    print("8-bit model", OUT, f"{os.path.getsize(OUT) / 1e6:.0f} MB")


if __name__ == "__main__":
    sys.exit(main())
