"""Small per-build brand settings for the F6201B desktop application."""

import json
from pathlib import Path


def load_brand() -> dict:
    return json.loads((Path(__file__).resolve().parent / "brand.json").read_text(encoding="utf-8"))
