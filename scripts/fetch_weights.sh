#!/usr/bin/env bash
# Pull the depth model into the local HF cache once, so nothing downloads
# during a live run.
set -e
python3 - << 'PY'
from transformers import pipeline
import torch
dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
pipeline("depth-estimation",
         model="depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf",
         device=dev)
print("depth model cached, device:", dev)
PY
