from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image


class TransDLANetAdapter:
    """Adapter/placeholder for a TransDLANet implementation.

    This adapter expects a callable object with a predict(image_path) -> detections
    interface provided by the implementation. If no implementation is available
    in the environment, the adapter raises an informative error telling the
    user how to provide the model directory / package.
    """

    def __init__(self, model_dir: Optional[Path] = None, checkpoint: Optional[str] = None, device: str = "cuda:0"):
        self.model_dir = Path(model_dir) if model_dir else None
        self.checkpoint = checkpoint
        self.device = device
        self.model: Any = None

    def load(self) -> None:
        # Try to import a local transdlanet package (user-provided)
        try:
            import transdlanet  # type: ignore

            self.model = transdlanet.load_model(model_dir=str(self.model_dir) if self.model_dir else None, checkpoint=self.checkpoint, device=self.device)
            return
        except Exception:
            pass

        # If import failed, provide an informative exception with instructions.
        msg = (
            "TransDLANet implementation not found in Python path.\n"
            "Please provide a TransDLANet implementation and checkpoint. Options:\n"
            "  1) Install a TransDLANet package into the environment (pip or editable).\n"
            "  2) Place a local implementation under a folder and pass --model-dir to the pilot.\n"
            "  3) If you have a GitHub implementation, clone it and set PYTHONPATH or install.\n"
            "The pilot expects the implementation to expose `load_model(model_dir, checkpoint, device)`\n"
            "and a model object with `predict(image_path)` returning a list of detections.\n"
        )

        raise RuntimeError(msg)

    def predict(self, image_path: str) -> List[Dict[str, Any]]:
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        # The adapter normalizes model outputs to a dict list with keys: class, score, bbox, mask
        raw = self.model.predict(image_path)

        detections: List[Dict[str, Any]] = []

        # Try to handle common shapes; otherwise, pass-through best-effort
        for item in raw:
            det: Dict[str, Any] = {
                "class": item.get("label") if isinstance(item, dict) else None,
                "confidence": float(item.get("score", 1.0)) if isinstance(item, dict) else 1.0,
                "bbox": item.get("bbox") if isinstance(item, dict) else None,
                "mask": item.get("mask") if isinstance(item, dict) else None,
                "raw": item,
            }
            detections.append(det)

        return detections
