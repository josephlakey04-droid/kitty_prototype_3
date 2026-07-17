"""
Pixel-art black cat sprite generator.

Eyes are drawn as empty sockets here - the caller (desktop_pet.py) paints
the pupils on top each frame, positioned toward the mouse cursor, so the
cat's gaze can follow it live instead of always staring straight ahead.
"""

from PIL import Image, ImageDraw

BLACK = (35, 33, 38, 255)
BLACK_SHINE = (55, 52, 58, 255)
DARK = (15, 14, 16, 255)
EYE = (255, 255, 255, 255)
PINK = (232, 150, 160, 255)

W, H = 32, 28

# how many animation frames each pose has
FRAME_COUNTS = {
    "idle": 1, "walk": 2, "sleep": 1, "alert": 1,
    "pounce": 1, "play": 2, "stretch": 1,
}


def _geometry(pose, direction, frame):
    """Shared layout math, also used by eye_anchor_points() so the pupils
    line up with wherever the sockets actually get drawn."""
    bob = 0
    if pose == "walk":
        bob = 1 if frame % 2 == 0 else 0
    if pose == "pounce":
        bob = -2
    if pose == "stretch":
        bob = 2
    body_y = 14 + bob
    head_cx = 22 if direction == "right" else 10
    if pose == "stretch":
        head_cx = 26 if direction == "right" else 6
    head_y = body_y - 10
    if pose == "sleep":
        head_y += 4
    if pose == "stretch":
        head_y += 6
    return body_y, head_cx, head_y


def eye_anchor_points(pose, direction, frame):
    """Returns [(x,y), (x,y)] socket centers in small-canvas coordinates,
    or None if the eyes are closed (sleeping) and have no gaze."""
    if pose == "sleep":
        return None
    _, head_cx, head_y = _geometry(pose, direction, frame)
    ex1, ex2 = head_cx - 4, head_cx + 4
    ey = head_y + 7
    return [(ex1, ey), (ex2, ey)]


def base_frame(pose, direction, frame):
    """The cat, fully drawn, EXCEPT for pupils - just empty white eye
    sockets (or closed lids if asleep). Small unscaled canvas."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    leg_shift = 0
    stretch = 0
    if pose == "walk":
        leg_shift = 2 if frame % 2 == 0 else -2
    if pose == "stretch":
        stretch = 5

    body_y, head_cx, head_y = _geometry(pose, direction, frame)

    if direction == "right":
        tail_pts = [(4, body_y + 4), (1, body_y - 2), (2, body_y - 8)]
    else:
        tail_pts = [(W - 4, body_y + 4), (W - 1, body_y - 2), (W - 2, body_y - 8)]
    if pose == "sleep":
        tail_pts = [(p[0], body_y + 6) for p in tail_pts]
    d.line(tail_pts, fill=BLACK, width=3)

    d.ellipse([10 - leg_shift, body_y + 8, 14 - leg_shift, body_y + 12], fill=BLACK)
    d.ellipse([18 + leg_shift, body_y + 8, 22 + leg_shift, body_y + 12], fill=BLACK)

    if pose == "stretch":
        d.ellipse([8 - stretch, body_y, 24 + stretch, body_y + 10], fill=BLACK)
    else:
        d.ellipse([8, body_y - 4, 24, body_y + 10], fill=BLACK)

    d.ellipse([9 - leg_shift, body_y + 8, 13 - leg_shift, body_y + 12], fill=BLACK)
    d.ellipse([19 + leg_shift, body_y + 8, 23 + leg_shift, body_y + 12], fill=BLACK)

    d.ellipse([head_cx - 8, head_y, head_cx + 8, head_y + 14], fill=BLACK)

    ear_lift = -3 if pose == "alert" else 0
    if pose == "play":
        ear_lift = -2 if frame % 2 == 0 else 1
    d.polygon([(head_cx - 7, head_y + 2), (head_cx - 9, head_y - 6 + ear_lift), (head_cx - 2, head_y - 1)], fill=BLACK)
    d.polygon([(head_cx - 6, head_y + 1), (head_cx - 7, head_y - 3 + ear_lift), (head_cx - 3, head_y)], fill=DARK)
    d.polygon([(head_cx + 7, head_y + 2), (head_cx + 9, head_y - 6 + ear_lift), (head_cx + 2, head_y - 1)], fill=BLACK)
    d.polygon([(head_cx + 6, head_y + 1), (head_cx + 7, head_y - 3 + ear_lift), (head_cx + 3, head_y)], fill=DARK)

    shine_x = head_cx - 6 if direction == "right" else head_cx + 6
    d.ellipse([shine_x - 2, head_y + 2, shine_x + 2, head_y + 6], fill=BLACK_SHINE)

    ex1, ex2 = head_cx - 4, head_cx + 4
    if pose == "sleep":
        d.line([(ex1 - 2, head_y + 7), (ex1 + 2, head_y + 7)], fill=DARK, width=1)
        d.line([(ex2 - 2, head_y + 7), (ex2 + 2, head_y + 7)], fill=DARK, width=1)
    elif pose in ("alert", "pounce", "play"):
        d.ellipse([ex1 - 3, head_y + 4, ex1 + 3, head_y + 10], fill=EYE)
        d.ellipse([ex2 - 3, head_y + 4, ex2 + 3, head_y + 10], fill=EYE)
    else:
        d.ellipse([ex1 - 2, head_y + 5, ex1 + 2, head_y + 9], fill=EYE)
        d.ellipse([ex2 - 2, head_y + 5, ex2 + 2, head_y + 9], fill=EYE)

    d.polygon([(head_cx - 1, head_y + 10), (head_cx + 1, head_y + 10), (head_cx, head_y + 11)], fill=PINK)

    if pose == "pounce":
        px = head_cx + (6 if direction == "right" else -6)
        d.ellipse([px - 2, body_y + 4, px + 2, body_y + 8], fill=BLACK)

    if pose == "play":
        paw_x = head_cx + (9 if direction == "right" else -9)
        paw_y = head_y + 4 if frame % 2 == 0 else head_y - 2
        d.ellipse([paw_x - 2, paw_y, paw_x + 2, paw_y + 4], fill=BLACK)

    return img


def with_pupils(img, anchors, gaze_dx, gaze_dy):
    """Returns a copy of img with a dark pupil drawn at each anchor,
    nudged by (gaze_dx, gaze_dy) pixels toward whatever the cat's looking at."""
    if not anchors:
        return img
    out = img.copy()
    d = ImageDraw.Draw(out)
    for ex, ey in anchors:
        px, py = ex + gaze_dx, ey + gaze_dy
        d.ellipse([px - 1, py - 1, px + 1, py + 1], fill=DARK)
    return out
