"""Monitor-bounded room around Nixi's base window."""


def split_room(x, y, w, h, xw, eh, side, mon):
    """Return left, right, top and total extra height within a monitor rect."""
    mx, my, mw, mh = mon
    left, right = side
    left_room = max(0, x - mx)
    right_room = max(0, mx + mw - x - w)
    down_room = max(0, my + mh - y - h)
    up_room = max(0, y - my)

    left = min(left_room, max(left, (xw + 1) // 2))
    right = min(right_room, max(right, (xw + 1) // 2))
    side_need = sum(side) if all(side) else 0
    missing = max(0, xw - left - right, side_need - left - right)
    add = min(missing, left_room - left)
    left += add
    right += min(missing - add, right_room - right)

    bottom = min(eh, down_room)
    top = min(eh - bottom, up_room)
    return left, right, top, bottom + top
