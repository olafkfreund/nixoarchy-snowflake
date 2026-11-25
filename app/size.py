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


def page_zoom(raw):
    try:
        value = float(raw)
        return max(0.5, min(2.5, value)) if math.isfinite(value) else 1.0
    except (TypeError, ValueError):
        return 1.0


def text_clamp(raw):
    try:
        value = float(raw)
        return max(0.6, min(2.0, value)) if math.isfinite(value) else 1.0
    except (TypeError, ValueError):
        return 1.0


def text_step(current, direction):
    if direction == "reset":
        return 1.0
    if direction not in ("up", "down"):
        raise ValueError(direction)
    return text_clamp(round(text_clamp(current) + (0.1 if direction == "up" else -0.1), 2))


def zooms(size, card_text, term_px, mon_w, mon_h, x0=None):
    z = clamp(size)
    target = max(10, min(28, term_px or 16)) * text_clamp(card_text)
    fit = min(mon_w / 750, mon_h / 460) if mon_w is not None and mon_h is not None else math.inf
    if x0 is not None and mon_w is not None:
        fit = min(fit, max((mon_w - x0) / 740, x0 / 400))
    page = page_zoom(max(min(target / 14, fit), z))
    return page, z / page, target
