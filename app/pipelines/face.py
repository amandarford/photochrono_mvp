# Minimal stubs wired for later plug-in of ONNX InsightFace models.
import numpy as np, cv2, os
from ..utils.db import DB


class FaceIndexer:
    def __init__(self, db: DB, model_path: str | None = None):
        self.db = db
        self.model_path = model_path

    def index(self) -> int:
        # MVP: generate placeholder embeddings (random) so clustering code can be tested.
        rows = self.db.list_photos(limit=10000)
        count = 0
        for r in rows:
            path = r["path"]
            if not os.path.exists(path):
                continue
            # Here you'd detect faces and compute embeddings.
            # For MVP, do nothing but count.
            count += 1
        return count
