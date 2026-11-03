from __future__ import annotations
from pathlib import Path
from typing import Iterable
import imageio.v2 as imageio
import numpy as np
from PIL import Image

def build_sequence_video(image_paths: Iterable[str | Path], out_path: str | Path,
                         fps: int = 2, max_width: int = 1000) -> Path:
    """Write frames incrementally; no multi-day in-memory PNG stack."""
    out_path = Path(out_path)
    paths = [Path(p) for p in image_paths if Path(p).exists()]
    if not paths:
        raise FileNotFoundError('No image frames for MP4')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with imageio.get_writer(out_path, fps=max(int(fps), 1), codec='libx264', macro_block_size=16) as writer:
        for path in paths:
            with Image.open(path) as im:
                img = im.convert('RGB')
                if img.width > max_width:
                    height = max(1, int(img.height * max_width / img.width))
                    img = img.resize((max_width, height), Image.Resampling.LANCZOS)
                writer.append_data(np.asarray(img))
    return out_path
