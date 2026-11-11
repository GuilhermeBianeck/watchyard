"""Verify a vehicle's movement using several parts of its visible body."""
import math
from itertools import product

import cv2


def vehicle_motion(previous, current, old_box, new_box):
    """Find textured patches that moved with the detected vehicle.

    Normalized correlation tolerates changes in brightness. Each patch must
    match better at a plausible new position than at its original position.
    """
    if previous.shape != current.shape:
        return False
    height, width = current.shape
    left, top, right, bottom = [value * size for value, size in zip(old_box, (width, height, width, height))]
    x0, y0, x1, y1 = [value * size for value, size in zip(new_box, (width, height, width, height))]
    half = min(13, max(4, int(min(right - left, bottom - top) * .12)))
    minimum = max(2, width * .003)
    textured = moving = 0
    for fx, fy in product((.25, .50, .75), repeat=2):
        x = round(left + fx * (right - left))
        y = round(top + fy * (bottom - top))
        dx, dy = x0 + fx * (x1 - x0) - x, y0 + fy * (y1 - y0) - y
        step = math.hypot(dx, dy)
        if step < minimum or not (half <= x < width - half and half <= y < height - half):
            continue
        patch = previous[y-half:y+half+1, x-half:x+half+1]
        if patch.std() < 5:
            continue
        textured += 1
        radius = round(min(2 * step + 4, width * .25))
        sx, sy = max(0, x - half - radius), max(0, y - half - radius)
        ex, ey = min(width, x + half + radius + 1), min(height, y + half + radius + 1)
        scores = cv2.matchTemplate(current[sy:ey, sx:ex], patch, cv2.TM_CCOEFF_NORMED)
        stationary = scores[y-half-sy, x-half-sx]
        _, best, _, (mx, my) = cv2.minMaxLoc(scores)
        dest_x, dest_y = sx + mx + half, sy + my + half
        if best < .72 or best - stationary < .13 or not (x0 <= dest_x <= x1 and y0 <= dest_y <= y1):
            continue
        tx, ty = dest_x - x, dest_y - y
        along = (tx * dx + ty * dy) / step
        across = abs(tx * dy - ty * dx) / step
        if max(minimum, .25 * step) <= along <= 1.9 * step and across <= .9 * along + 4:
            moving += 1
    return moving >= 3 and moving * 2 >= textured
