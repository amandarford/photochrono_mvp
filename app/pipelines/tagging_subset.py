from dataclasses import dataclass
from typing import List, Tuple
import numpy as np

@dataclass
class TaggingConfig:
    phash_dist_max: int = 6
    time_gap_hours: int = 18
    per_event_cap: int = 5
    face_cluster_thresh: float = 0.6
    target_size_min: int = 300
    target_size_max: int = 800

def build_tagging_batch(db, cfg: TaggingConfig) -> List[int]:
    # 1) representatives from phash groups
    reps = compute_phash_representatives(db, cfg.phash_dist_max)

    # 2) date anchors
    anchors = compute_date_anchors(db, reps, cfg.time_gap_hours)

    # 3) face detect + embeddings + clustering on reps
    face_sel = select_face_exemplars(db, reps, cfg.face_cluster_thresh)

    # 4) uncertain EXIF
    exif_uncertain = fetch_uncertain_exif(db, reps)

    # 5) enforce diversity caps and size bounds
    batch = diversify_and_trim(anchors + face_sel + exif_uncertain,
                               per_event_cap=cfg.per_event_cap,
                               min_size=cfg.target_size_min,
                               max_size=cfg.target_size_max)
    return batch
