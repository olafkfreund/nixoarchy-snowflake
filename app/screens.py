"""Pure monitor geometry for dragging and restoring the overlay."""


def mon_strict(geoms, x, y):
    for i, (gx, gy, w, h) in enumerate(geoms):
        if gx <= x < gx + w and gy <= y < gy + h:
            return i
    return None


def dock_edge(geoms, cur, cursor, reach=40):
    x, y, w, h = geoms[cur]
    cx, cy = cursor
    edges = (("top", cy - y, (cx, y - 1)),
             ("bottom", y + h - 1 - cy, (cx, y + h)),
             ("left", cx - x, (x - 1, cy)),
             ("right", x + w - 1 - cx, (x + w, cy)))
    for edge, distance, probe in sorted(edges, key=lambda item: item[1]):
        if 0 <= distance < reach and mon_strict(geoms, *probe) is None:
            return edge
    return None


def drag_place(geoms, cursor, off, cur):
    i = mon_strict(geoms, *cursor)
    if i is None:
        i = cur
    x, y, _, _ = geoms[i]
    return i, cursor[0] - off[0] - x, cursor[1] - off[1] - y


def clamp_on(geom, x, y, w, h):
    return (min(max(x, 0), max(0, geom[2] - w)),
            min(max(y, 0), max(0, geom[3] - h)))


def outer_clamp(geoms, cur, gx, gy, w, h, ball):
    x, y, mw, mh = geoms[cur]
    bx, by = gx + ball[0], gy + ball[1]
    nx, ny = gx, gy
    if gx < x and mon_strict(geoms, x - 1, by) is None:
        nx = x
    elif gx > x + max(0, mw - w) and mon_strict(geoms, x + mw, by) is None:
        nx = x + max(0, mw - w)
    if gy < y and mon_strict(geoms, bx, y - 1) is None:
        ny = y
    elif gy > y + max(0, mh - h) and mon_strict(geoms, bx, y + mh) is None:
        ny = y + max(0, mh - h)
    return nx, ny, gx - nx, gy - ny


def pick_monitor(saved, names, n):
    if saved.get("name"):
        return next((i for name, i in names if name == saved["name"]), None)
    try:
        i = int(saved["mon"])
    except (KeyError, TypeError, ValueError):
        return None
    return i if 0 <= i < n else None


def pos_dict(p, mon, x, y, name, bar):
    p.update(mon=mon, x=x, y=y)
    if name is None:
        p.pop("name", None)
    else:
        p["name"] = name
    if name and not bar:
        p.setdefault("mons", {})[name] = [x, y]
    return p


def focus_blocked(dragging, pmoving, dpos, now, drag_end_t):
    return bool(dragging or pmoving or dpos is not None or
                (drag_end_t is not None and now < drag_end_t + 0.6))
