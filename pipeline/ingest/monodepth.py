"""Monocular metric depth from a single RGB image.

Depth Anything V2, metric indoor, small. Chosen over Depth Pro after testing
on the target laptop: Depth Pro needed 50 s to load and 47-77 s per image at
half precision, and still ran out of GPU memory at full precision. This one
loads in seconds and runs in about 0.13 s per image on Apple silicon, which
is what a live walk-in test can tolerate.

Disclosure: pretrained weights, downloaded once to the local HF cache, no
network calls at inference time."""

import numpy as np

MODEL_ID = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"

_pipe = None


def _device():
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load():
    global _pipe
    if _pipe is None:
        from transformers import pipeline
        _pipe = pipeline("depth-estimation", model=MODEL_ID, device=_device())
    return _pipe


def predict(image):
    """PIL image -> float32 depth in metres at the image's own resolution."""
    from PIL import Image
    pipe = load()
    out = pipe(image)["predicted_depth"].squeeze().float().cpu().numpy()
    if out.shape != (image.height, image.width):
        out = np.array(Image.fromarray(out).resize((image.width, image.height),
                                                   Image.BILINEAR))
    return out.astype(np.float32)
