"""Pure decisions for "Nixi steps aside while nixi's card is open" (S23); window.py does the moving."""

CARD_BAND = 0.38      # the card is centred 38% of the way down
CARD_MAX = 0.7        # its widest, as a share of the screen: nixi caps it there whatever its font/display scale
VISIBLE_W = 220       # how much of his 340px strip is him
STRIP_W, MARGIN = 340, 10   # his window strip, and target()'s distance from the edge


def layer_event(line):
    """b'openlayer>>nixi' → 'open', b'closelayer>>nixi' → 'close'. Exact namespace: 'nixi-companion' is himself."""
    for ev in ("open", "close"):
        if line.strip() == f"{ev}layer>>nixi".encode():
            return ev
    return None


def card_monitor(layers, ns="nixi"):
    """Hyprland's `j/layers` ({monitor: {levels: {n: [{namespace}]}}}) → the monitor holding that namespace, or None."""
    for mon, v in (layers or {}).items():
        for lv in (v.get("levels") or {}).values():
            if any(x.get("namespace") == ns for x in lv):
                return mon
    return None


def side(x, w, mon_w):
    """The nearer edge for a strip at x of width w."""
    return "left" if x + w / 2 < mon_w / 2 else "right"


def free_gap(mon_w):
    """Worst-case room each side of the card (its width in px depends on scales we can't see, the cap doesn't)."""
    return mon_w * (1 - CARD_MAX) / 2


def plan(mon_w, has_other_monitor):
    """'side' if he fits beside the card, else 'monitor' if there is another screen, else 'hover'."""
    need = MARGIN + (STRIP_W - VISIBLE_W) / 2 + VISIBLE_W   # he sits inside a padded strip, a margin from the edge
    return "side" if free_gap(mon_w) >= need else "monitor" if has_other_monitor else "hover"


def target(mon_w, mon_h, x, w, h, strip=10):
    """Where beside the card he goes: the nearer edge, at the card's band, clamped to the monitor (margins)."""
    tx = strip if side(x, w, mon_w) == "left" else mon_w - w - strip
    ty = int(mon_h * CARD_BAND - h / 2)
    return max(0, tx), min(max(ty, 0), max(0, mon_h - h))


def may_return(now, parked):
    """Go back only if he is still where we put him (not dragged or moved while aside)."""
    return parked is not None and tuple(now) == tuple(parked)
