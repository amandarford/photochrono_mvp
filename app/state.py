from dataclasses import dataclass, field


@dataclass
class AppState:
    face_model_path: str | None = None  # path to ONNX model (optional in MVP)
    date_confidence_threshold: float = 0.75
    use_sidecars: bool = True
