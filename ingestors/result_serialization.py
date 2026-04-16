"""Shared helpers for serializing task result dataclasses to JSON-safe dicts."""

from dataclasses import asdict
from enum import Enum
from typing import Any


def result_to_dict(result) -> dict[str, Any]:
    """Convert a dataclass result to a JSON-serializable dict, converting enums to their values."""
    return {
        k: [i.value for i in v]
        if isinstance(v, list) and v and isinstance(v[0], Enum)
        else v.value
        if isinstance(v, Enum)
        else v
        for k, v in asdict(result).items()
    }
