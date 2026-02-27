# physics.py - Shared physics engine for K-Maze
import math

# === CANONICAL CONSTANTS ===
GRAVITY = [0.0, 400.0]
DRAG = 0.995
BALL_R = 10
DT = 1.0 / 60.0
RESTITUTION = 0.85
K_RESTITUTION = 1.05  # K-gates are springy/bouncier than walls
PLAYFIELD_W = 800
PLAYFIELD_H = 600

# K shape: relative points forming the deflector
K_REL_POINTS = [
    [0, -45], [0, 45],           # stem
    [30, 30], [0, 0], [30, -30], # upper arm + connect
    [0, -45]                     # close
]


def rotate_points(points, angle, center):
    """Rotate a list of [x,y] points around center by angle (radians)."""
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return [
        [center[0] + px * cos_a - py * sin_a,
         center[1] + px * sin_a + py * cos_a]
        for px, py in points
    ]


def reflect_ball_over_line(pos, vel, p1, p2, r, restitution=None):
    """Reflect ball off line segment p1->p2. Modifies pos/vel in-place. Returns True if collision."""
    if restitution is None:
        restitution = RESTITUTION
    line_vec = [p2[0] - p1[0], p2[1] - p1[1]]
    line_len_sq = line_vec[0]**2 + line_vec[1]**2
    if line_len_sq == 0:
        return False
    d = ((pos[0] - p1[0]) * line_vec[0] + (pos[1] - p1[1]) * line_vec[1]) / line_len_sq
    t = max(0, min(1, d))
    closest = [p1[0] + t * line_vec[0], p1[1] + t * line_vec[1]]
    dx = pos[0] - closest[0]
    dy = pos[1] - closest[1]
    dist = math.sqrt(dx**2 + dy**2)
    if dist > r or dist == 0:
        return False
    nx = dx / dist
    ny = dy / dist
    penetration = r - dist
    pos[0] += nx * penetration * 1.001
    pos[1] += ny * penetration * 1.001
    dot = vel[0] * nx + vel[1] * ny
    vel[0] -= 2 * dot * nx
    vel[1] -= 2 * dot * ny
    vel[0] *= restitution
    vel[1] *= restitution
    return True


def detect_collision(pos, p1, p2, r):
    """Detect hit without modifying pos/vel."""
    line_vec = [p2[0] - p1[0], p2[1] - p1[1]]
    line_len_sq = line_vec[0]**2 + line_vec[1]**2
    if line_len_sq == 0:
        return False
    d = ((pos[0] - p1[0]) * line_vec[0] + (pos[1] - p1[1]) * line_vec[1]) / line_len_sq
    t = max(0, min(1, d))
    closest = [p1[0] + t * line_vec[0], p1[1] + t * line_vec[1]]
    dx = pos[0] - closest[0]
    dy = pos[1] - closest[1]
    dist = math.sqrt(dx**2 + dy**2)
    return dist < r


def dist_to_line(pos, p1, p2):
    """Distance from point to nearest point on line segment."""
    line_vec = [p2[0] - p1[0], p2[1] - p1[1]]
    line_len_sq = line_vec[0]**2 + line_vec[1]**2
    if line_len_sq == 0:
        return math.hypot(pos[0] - p1[0], pos[1] - p1[1])
    d = ((pos[0] - p1[0]) * line_vec[0] + (pos[1] - p1[1]) * line_vec[1]) / line_len_sq
    t = max(0, min(1, d))
    closest = [p1[0] + t * line_vec[0], p1[1] + t * line_vec[1]]
    return math.hypot(pos[0] - closest[0], pos[1] - closest[1])


def point_in_circle(pos, center, radius):
    return math.hypot(pos[0] - center[0], pos[1] - center[1]) < radius


def simulate_ball(pos, vel, walls, ks, max_steps=600, target=None,
                   record_trajectory=True):
    """Simulate a single ball using canonical physics.

    Args:
        target: Optional dict {'pos': [x,y], 'r': radius} for inline hit check.
        record_trajectory: If False, returns empty trajectory (faster).

    Returns: (final_pos, final_vel, steps_survived, wall_hits, k_hits, trajectory)
        If target is given, also sets trajectory to include min_dist and hit info
        as the last element: {'min_dist': float, 'hit': bool}
    """
    pos = pos[:]
    vel = vel[:]
    k_hits = 0
    wall_hits = 0
    trajectory = [pos[:]] if record_trajectory else []

    # Precompute K segments once (avoids trig every step)
    k_segments = []
    for k in ks:
        rot_pts = rotate_points(K_REL_POINTS, k['angle'], k['center'])
        segs = [(rot_pts[i], rot_pts[i + 1]) for i in range(len(rot_pts) - 1)]
        k_segments.append(segs)

    # Target tracking
    tgt_x = tgt_y = tgt_r = 0.0
    min_dist = float('inf')
    hit_target = False
    if target:
        tgt_pos = target['pos'] if isinstance(target, dict) else target[:2]
        tgt_x, tgt_y = tgt_pos[0], tgt_pos[1]
        tgt_r = (target.get('r', 25) if isinstance(target, dict) else 25) + BALL_R

    gx, gy = GRAVITY
    drag = DRAG
    ball_r = BALL_R
    pw, ph = PLAYFIELD_W, PLAYFIELD_H

    for step in range(max_steps):
        vel[0] += gx * DT
        vel[1] += gy * DT
        pos[0] += vel[0] * DT
        pos[1] += vel[1] * DT
        vel[0] *= drag
        vel[1] *= drag

        # Out of bounds = dead
        if pos[0] < 0 or pos[0] > pw or pos[1] > ph or pos[1] < -50:
            break

        # Wall reflections
        for wall in walls:
            if reflect_ball_over_line(pos, vel, wall[0], wall[1], ball_r):
                wall_hits += 1

        # K shape reflections (precomputed segments)
        for segs in k_segments:
            for p1, p2 in segs:
                if reflect_ball_over_line(pos, vel, p1, p2, ball_r, K_RESTITUTION):
                    k_hits += 1

        # Inline target check
        if target:
            dx = pos[0] - tgt_x
            dy = pos[1] - tgt_y
            d = math.sqrt(dx * dx + dy * dy)
            if d < min_dist:
                min_dist = d
            if d < tgt_r:
                hit_target = True

        if record_trajectory:
            trajectory.append(pos[:])
    else:
        step = max_steps

    if target:
        trajectory.append({'min_dist': min_dist, 'hit': hit_target})

    return pos, vel, step, wall_hits, k_hits, trajectory
