"""Companion zoom limits and keyboard steps."""
import math


def clamp(raw):
    try:
        value = float(raw)
        return max(0.5, min(1.25, value)) if math.isfinite(value) else 0.75
    except (TypeError, ValueError):
        return 0.75


def step(current, direction):
    if direction == "reset":
        return 0.75
    if direction not in ("up", "down"):
        raise ValueError(direction)
    return clamp(round(clamp(current) + (0.1 if direction == "up" else -0.1), 2))
