"""Platform-shelf level generator for K-Maze.

Generates mazes suited to ball-physics gameplay: horizontal shelves with gaps
that balls fall through, K shapes at strategic deflection points, and optional
vertical/diagonal walls for variety.

Usage:
    python3 maze_gen.py                          # defaults: 50 mixed-difficulty courses
    python3 maze_gen.py -n 10 -d 1 --slope 0.15  # 10 easy courses, steep slope
    python3 maze_gen.py --k-bounce 1.3 --gravity 250  # floaty, super-bouncy K-gates
    python3 maze_gen.py --gap-width 40-60 -d 3   # narrow gaps, hard difficulty
"""
import argparse
import random
import math
import json
from physics import PLAYFIELD_W, PLAYFIELD_H, RESTITUTION, K_RESTITUTION, DRAG
from stock_shapes import get_component, list_components, translate_component, COMPONENT_REGISTRY

# Golden ratio constants for aesthetic spacing
PHI = (1 + math.sqrt(5)) / 2       # 1.618...
INV_PHI = 1.0 / PHI                 # 0.618...

THEME_ANGLE_SETS = {
    'gentle':   (math.radians(15), math.radians(-15)),
    'moderate': (math.radians(30), math.radians(-30)),
    'steep':    (math.radians(45), math.radians(-45)),
}

TEMPLATES = ['zigzag', 'symmetric', 'pinball', 'cascade',
             'maze', 'fractal', 'factory', 'house', 'diamond', 'spiral']


def generate_course(seed=None, difficulty=1, slope=None, gap_width_range=(50, 80)):
    """Generate a single playable K-Maze course.

    Args:
        seed: Random seed for reproducibility.
        difficulty: 1-3, controls shelf count, gap count, K placement.
        slope: Shelf slope (Y drop per X pixel). None = random 0.04-0.10.
        gap_width_range: (min, max) gap width in pixels.
    """
    if seed is not None:
        random.seed(seed)

    walls = []
    ks = []

    # Boundary walls (left, right, bottom — top open for ball entry)
    walls.append([[0, 0], [0, PLAYFIELD_H]])
    walls.append([[PLAYFIELD_W, 0], [PLAYFIELD_W, PLAYFIELD_H]])
    walls.append([[0, PLAYFIELD_H], [PLAYFIELD_W, PLAYFIELD_H]])

    # Shelf parameters
    num_shelves = 2 + difficulty  # 3, 4, or 5 shelves
    shelf_spacing = (PLAYFIELD_H - 120) / (num_shelves + 1)

    shelf_ys = []
    for i in range(1, num_shelves + 1):
        y = 80 + i * shelf_spacing + random.uniform(-20, 20)
        y = max(100, min(PLAYFIELD_H - 80, y))
        shelf_ys.append(int(y))
    shelf_ys.sort()

    # Shelves slope down left-to-right so the ball naturally rolls toward the target
    actual_slope = slope if slope is not None else random.uniform(0.04, 0.10)
    gap_positions = []

    for shelf_idx, sy in enumerate(shelf_ys):
        num_gaps = random.randint(1, 1 + difficulty)
        shelf_left = random.randint(20, 60)
        shelf_right = PLAYFIELD_W - random.randint(20, 60)
        gap_width = random.randint(gap_width_range[0], gap_width_range[1])

        gaps = []
        for _ in range(num_gaps):
            for _attempt in range(20):
                gx = random.randint(shelf_left + 40, max(shelf_left + 41, shelf_right - 40 - gap_width))
                too_close = any(abs(gx - eg[0]) < gap_width + 30 for eg in gaps)
                if not too_close:
                    gaps.append((gx, gx + gap_width))
                    break

        gaps.sort(key=lambda g: g[0])

        # Build wall segments around gaps (sloped: Y increases with X)
        def shelf_y(x, _slope=actual_slope, _sy=sy, _left=shelf_left):
            return int(_sy + (x - _left) * _slope)

        current_x = shelf_left
        for gap_start, gap_end in gaps:
            if current_x < gap_start:
                walls.append([[current_x, shelf_y(current_x)], [gap_start, shelf_y(gap_start)]])
            gap_mid_x = (gap_start + gap_end) / 2
            gap_positions.append({
                'x': gap_mid_x,
                'y': shelf_y(int(gap_mid_x)),
                'width': gap_end - gap_start,
                'shelf_idx': shelf_idx,
            })
            current_x = gap_end
        if current_x < shelf_right:
            walls.append([[current_x, shelf_y(current_x)], [shelf_right, shelf_y(shelf_right)]])

    # Optional vertical guide walls
    num_verticals = random.randint(0, difficulty)
    for _ in range(num_verticals):
        vx = random.randint(100, PLAYFIELD_W - 100)
        vy_top = random.choice(shelf_ys) if shelf_ys else 200
        vy_bottom = vy_top + random.randint(40, 120)
        walls.append([[vx, vy_top], [vx, min(vy_bottom, PLAYFIELD_H - 50)]])

    # Optional diagonal deflector walls
    num_diags = random.randint(0, difficulty)
    for _ in range(num_diags):
        dx = random.randint(100, PLAYFIELD_W - 100)
        dy = random.randint(100, PLAYFIELD_H - 100)
        angle = random.choice([math.pi / 6, -math.pi / 6, math.pi / 4, -math.pi / 4])
        length = random.randint(60, 120)
        walls.append([
            [dx, dy],
            [int(dx + length * math.cos(angle)), int(dy + length * math.sin(angle))]
        ])

    # Place K shapes near gaps (strategic deflection points)
    num_ks = min(len(gap_positions), 1 + difficulty)
    if gap_positions:
        selected_gaps = random.sample(gap_positions, min(num_ks, len(gap_positions)))
        for gap in selected_gaps:
            kx = gap['x'] + random.uniform(-30, 30)
            ky = gap['y'] - random.randint(35, 70)
            kx = max(60, min(PLAYFIELD_W - 60, kx))
            ky = max(60, min(PLAYFIELD_H - 60, ky))
            ks.append({
                'center': [round(kx, 1), round(ky, 1)],
                'angle': random.uniform(0, math.pi * 2),
            })

    # Extra K shapes between shelves
    extra_ks = random.randint(0, 1 + difficulty // 2)
    for _ in range(extra_ks):
        kx = random.uniform(100, PLAYFIELD_W - 100)
        if len(shelf_ys) >= 2:
            idx = random.randint(0, len(shelf_ys) - 2)
            ky = (shelf_ys[idx] + shelf_ys[idx + 1]) / 2 + random.uniform(-20, 20)
        else:
            ky = random.uniform(150, 450)
        ks.append({
            'center': [round(kx, 1), round(ky, 1)],
            'angle': random.uniform(0, math.pi * 2),
        })

    # Start (top-left area) and target (bottom-right area)
    start = [random.randint(60, 200), random.randint(30, 60)]
    target_x = random.randint(PLAYFIELD_W - 200, PLAYFIELD_W - 60)
    target_y = random.randint(PLAYFIELD_H - 80, PLAYFIELD_H - 40)
    target = {'pos': [target_x, target_y], 'r': 25}

    return {
        'walls': walls,
        'ks': ks,
        'start': start,
        'target': target,
        'name': f'Course {seed}' if seed is not None else 'Course',
    }


def generate_component_course(seed=None, difficulty=1):
    """Generate a course by composing tested components vertically.

    Stacks 2-4 components top-to-bottom, connecting each exit to the next
    entry. This guarantees a structural path through the level.
    """
    if seed is not None:
        random.seed(seed)

    walls = [
        [[0, 0], [0, PLAYFIELD_H]],
        [[PLAYFIELD_W, 0], [PLAYFIELD_W, PLAYFIELD_H]],
        [[0, PLAYFIELD_H], [PLAYFIELD_W, PLAYFIELD_H]],
    ]
    ks_list = []

    # Categorize components by tag
    vertical_names = [n for n in COMPONENT_REGISTRY
                      if any(t in ("vertical", "funnel", "gate")
                             for t in get_component(n)["tags"])]
    redirect_names = [n for n in COMPONENT_REGISTRY
                      if any(t in ("redirect", "trampoline", "room", "bouncy")
                             for t in get_component(n)["tags"])]
    all_names = list(COMPONENT_REGISTRY.keys())

    num_components = 1 + difficulty  # 2, 3, or 4
    start_x = random.randint(150, PLAYFIELD_W - 150)
    start_y = 40

    current_x = start_x
    current_y = 80

    for i in range(num_components):
        # Last component: funnel to guide to target
        if i == num_components - 1:
            candidates = [n for n in COMPONENT_REGISTRY if "funnel" in n]
        elif random.random() < 0.4 and redirect_names:
            candidates = redirect_names
        elif vertical_names:
            candidates = vertical_names
        else:
            candidates = all_names

        comp_name = random.choice(candidates)
        comp = get_component(comp_name)
        if comp is None:
            continue

        bbox = comp["bbox"]
        comp_w = bbox[2] - bbox[0]

        # Place centered on current_x, at current_y
        place_x = max(20, min(PLAYFIELD_W - comp_w - 20, current_x - comp_w / 2))
        place_y = current_y

        # Skip if component would overflow playfield
        if place_y + (bbox[3] - bbox[1]) > PLAYFIELD_H - 60:
            break

        placed = translate_component(comp, place_x - bbox[0], place_y - bbox[1])
        walls.extend(placed["walls"])
        ks_list.extend(placed["ks"])

        # Move to exit of this component
        exit_ = placed["exit"]
        current_x = (exit_["a"][0] + exit_["b"][0]) / 2
        current_y = (exit_["a"][1] + exit_["b"][1]) / 2 + 15

    target_x = max(40, min(PLAYFIELD_W - 40, int(current_x)))
    target_y = min(PLAYFIELD_H - 30, int(current_y + 30))

    return {
        "walls": walls,
        "ks": ks_list,
        "start": [start_x, start_y],
        "target": {"pos": [target_x, target_y], "r": 25},
        "name": f"Comp {seed}" if seed is not None else "Comp Course",
    }


def _snap(v, step=10):
    """Snap a coordinate to the nearest grid step for cleaner lines."""
    return round(v / step) * step


def _wall_from_center(cx, cy, angle, length):
    """Build a [[x1,y1],[x2,y2]] wall from center, angle, length."""
    dx = length / 2 * math.cos(angle)
    dy = length / 2 * math.sin(angle)
    return [[_snap(cx - dx), _snap(cy - dy)],
            [_snap(cx + dx), _snap(cy + dy)]]


def _phi_positions(start, end, count):
    """Distribute `count` positions between start..end using golden ratio.

    Produces decreasing gaps (large at top, small at bottom) creating
    a natural acceleration feel matching gravity.
    """
    if count <= 0:
        return []
    if count == 1:
        return [start + (end - start) * INV_PHI]
    # Build phi-weighted gaps: each gap = previous / PHI
    ratios = [1.0 / (PHI ** i) for i in range(count + 1)]
    total = sum(ratios)
    positions = []
    y = start
    for r in ratios[:-1]:
        y += (end - start) * r / total
        positions.append(_snap(y))
    return positions


def _generate_zigzag(difficulty, theme, W, H):
    """Zigzag descent: alternating angled shelves from top to bottom."""
    walls = []
    ks = []
    angle_pos, angle_neg = theme
    num_shelves = 2 + difficulty  # 3-5

    shelf_ys = _phi_positions(80, H - 80, num_shelves)
    margin = 40
    gap_w = random.randint(50, 70)

    for i, sy in enumerate(shelf_ys):
        # Alternate direction: even shelves lean right, odd lean left
        angle = angle_pos if i % 2 == 0 else angle_neg
        shelf_len = W - 2 * margin

        # Gap position along the shelf (phi-positioned)
        if i % 2 == 0:
            gap_x = _snap(margin + shelf_len * INV_PHI)
        else:
            gap_x = _snap(margin + shelf_len * (1 - INV_PHI))

        # Left segment (before gap)
        if gap_x - gap_w / 2 > margin + 30:
            walls.append(_wall_from_center(
                (margin + gap_x - gap_w / 2) / 2, sy,
                angle, gap_x - gap_w / 2 - margin))

        # Right segment (after gap)
        if gap_x + gap_w / 2 < W - margin - 30:
            walls.append(_wall_from_center(
                (gap_x + gap_w / 2 + W - margin) / 2, sy,
                angle, W - margin - gap_x - gap_w / 2))

        # K-gate at gap apex — slightly above the gap
        ks.append({
            'center': [_snap(gap_x), _snap(sy - 40)],
            'angle': random.choice([angle_pos, angle_neg, 0]),
        })

    # Extra K between first and second shelf for complexity
    if len(shelf_ys) >= 2 and difficulty >= 2:
        mid_y = (shelf_ys[0] + shelf_ys[1]) / 2
        ks.append({
            'center': [_snap(W / 2), _snap(mid_y)],
            'angle': random.uniform(0, 2 * math.pi),
        })

    # Start above the first gap so ball drops right through
    first_gap_x = _snap(margin + (W - 2 * margin) * INV_PHI)
    return walls, ks, {'template': 'zigzag', 'symmetry': None,
                       'start': [first_gap_x, _snap(40)],
                       'target': [_snap(W - margin - 30), _snap(H - 30)]}


def _generate_symmetric(difficulty, theme, W, H):
    """Bilateral symmetry around x=W/2."""
    walls = []
    ks = []
    angle_pos, angle_neg = theme
    axis = W / 2
    num_layers = 2 + difficulty  # 3-5

    layer_ys = _phi_positions(80, H - 80, num_layers)

    for i, ly in enumerate(layer_ys):
        # Chamber half-width alternates phi proportions
        if i % 2 == 0:
            half_w = _snap((axis - 40) * INV_PHI)
        else:
            half_w = _snap((axis - 40) * (1 - INV_PHI))

        wall_len = half_w - 20
        if wall_len < 40:
            wall_len = 40

        # Left wall — angled inward
        angle = angle_pos if i % 2 == 0 else angle_neg
        lx = _snap(axis - half_w / 2 - 20)
        walls.append(_wall_from_center(lx, ly, angle, wall_len))

        # Mirror: right wall
        rx = _snap(2 * axis - lx)
        walls.append(_wall_from_center(rx, ly, -angle, wall_len))

        # Short horizontal connector below for visual framing
        if i < num_layers - 1:
            conn_y = _snap(ly + 25)
            conn_len = half_w * 0.4
            # Left connector
            walls.append(_wall_from_center(
                _snap(axis - half_w * 0.7), conn_y, 0, conn_len))
            # Mirror connector
            walls.append(_wall_from_center(
                _snap(axis + half_w * 0.7), conn_y, 0, conn_len))

    # K-gates on the symmetry axis
    k_ys = _phi_positions(layer_ys[0] - 20, layer_ys[-1] + 20,
                           min(num_layers, 2 + difficulty))
    for ky in k_ys:
        ks.append({
            'center': [_snap(axis), _snap(ky)],
            'angle': random.choice([0, math.pi / 4, -math.pi / 4]),
        })

    # Extra K-gates flanking the axis for harder difficulties
    if difficulty >= 2 and len(layer_ys) >= 2:
        flank_y = (layer_ys[0] + layer_ys[1]) / 2
        offset = _snap(axis * INV_PHI * 0.5)
        ks.append({'center': [_snap(axis - offset), _snap(flank_y)],
                   'angle': angle_pos})
        ks.append({'center': [_snap(axis + offset), _snap(flank_y)],
                   'angle': angle_neg})

    # Start above first layer on axis, target below last layer
    return walls, ks, {'template': 'symmetric', 'symmetry': 'bilateral',
                       'symmetry_axis': axis,
                       'start': [_snap(axis), _snap(layer_ys[0] - 50)],
                       'target': [_snap(axis), _snap(H - 40)]}


def _generate_pinball(difficulty, theme, W, H):
    """Pinball machine: horizontal shelves with gaps and K-gate deflectors.

    Ball falls through gaps in shelves. K-gates sit between shelf rows
    to redirect the ball toward the next gap. V-deflectors are decorative
    walls flanking the gaps that channel the ball.
    """
    walls = []
    ks = []
    angle_pos, angle_neg = theme
    num_rows = 2 + difficulty  # 3-5

    row_ys = _phi_positions(100, H - 80, num_rows)

    for i, ry in enumerate(row_ys):
        margin = 40
        # Gap alternates left/right (phi-positioned)
        gap_x = _snap(margin + (W - 2 * margin) *
                      (INV_PHI if i % 2 == 0 else 1 - INV_PHI))
        gap_w = random.randint(55, 75)  # wide enough for ball

        # Shelf segments on either side of gap
        if gap_x - gap_w / 2 > margin + 30:
            walls.append([[_snap(margin), _snap(ry)],
                          [_snap(gap_x - gap_w / 2), _snap(ry)]])
        if gap_x + gap_w / 2 < W - margin - 30:
            walls.append([[_snap(gap_x + gap_w / 2), _snap(ry)],
                          [_snap(W - margin), _snap(ry)]])

        # Small angled deflectors beside the gap (visual framing, not blocking)
        dlen = random.randint(40, 60)
        walls.append(_wall_from_center(
            _snap(gap_x - gap_w / 2 - 15), _snap(ry - 20),
            angle_pos, dlen * 0.4))
        walls.append(_wall_from_center(
            _snap(gap_x + gap_w / 2 + 15), _snap(ry - 20),
            angle_neg, dlen * 0.4))

    # K-gates between rows — positioned to redirect ball toward next gap
    for i in range(len(row_ys) - 1):
        mid_y = _snap((row_ys[i] + row_ys[i + 1]) / 2)
        # Next gap position
        next_gap_x = _snap(40 + (W - 80) *
                           (INV_PHI if (i + 1) % 2 == 0 else 1 - INV_PHI))
        ks.append({
            'center': [_snap((W / 2 + next_gap_x) / 2), mid_y],
            'angle': random.choice([angle_pos, angle_neg, 0]),
        })

    # Start above the first gap so ball drops into first row
    first_gap_x = _snap(40 + (W - 80) * INV_PHI)
    return walls, ks, {'template': 'pinball', 'symmetry': None,
                       'start': [first_gap_x, _snap(40)],
                       'target': [_snap(W / 2), _snap(H - 30)]}


def _generate_cascade(difficulty, theme, W, H):
    """Cascading platforms with gaps: ball drops through gaps in each level.

    Platforms get shorter by golden ratio. Each has a gap. K-gates between
    platforms redirect ball toward the next gap.
    """
    walls = []
    ks = []
    angle_pos, angle_neg = theme
    num_platforms = 3 + difficulty  # 4-6

    plat_ys = _phi_positions(80, H - 70, num_platforms)

    # Each platform shorter than the last by INV_PHI
    max_w = W - 100
    plat_widths = []
    w = max_w
    for _ in range(num_platforms):
        plat_widths.append(_snap(max(120, w)))
        w *= INV_PHI

    gap_positions = []  # track for K-gate placement

    for i, (py, pw) in enumerate(zip(plat_ys, plat_widths)):
        # Alternate left/right alignment
        if i % 2 == 0:
            px = _snap(50 + (W - 100 - pw) * 0.2)
        else:
            px = _snap(50 + (W - 100 - pw) * 0.8)

        # Gap in platform (phi-positioned)
        gap_frac = INV_PHI if i % 2 == 0 else 1 - INV_PHI
        gap_x = _snap(px + pw * gap_frac)
        gap_w = max(50, _snap(pw * 0.15))
        gap_positions.append((_snap(gap_x), _snap(py)))

        # Platform segments around the gap
        if gap_x - gap_w / 2 > px + 20:
            walls.append([[_snap(px), _snap(py)],
                          [_snap(gap_x - gap_w / 2), _snap(py)]])
        if gap_x + gap_w / 2 < px + pw - 20:
            walls.append([[_snap(gap_x + gap_w / 2), _snap(py)],
                          [_snap(px + pw), _snap(py)]])

        # Angled lip at non-gap end to direct ball toward gap
        lip_x = px if gap_frac > 0.5 else px + pw
        lip_dir = angle_pos if i % 2 == 0 else angle_neg
        walls.append(_wall_from_center(
            _snap(lip_x), _snap(py - 15), lip_dir, 40))

    # K-gates between platforms — redirect ball toward next gap
    for i in range(len(plat_ys) - 1):
        mid_y = _snap((plat_ys[i] + plat_ys[i + 1]) / 2)
        ks.append({
            'center': [_snap(gap_positions[i][0]), mid_y],
            'angle': random.choice([0, angle_pos, angle_neg]),
        })

    # Start above first gap, target below last gap
    start_x = gap_positions[0][0] if gap_positions else _snap(80)
    start_y = _snap(plat_ys[0] - 45)
    target_x = gap_positions[-1][0] if gap_positions else _snap(W - 80)
    target_y = _snap(plat_ys[-1] + 40)

    return walls, ks, {'template': 'cascade', 'symmetry': None,
                       'start': [start_x, start_y],
                       'target': [target_x, target_y]}


def _maze_backtrack(cols, rows, seed=None):
    """Generate a perfect maze using recursive backtracker.

    Returns grid[row][col] with sets of open directions ('N','S','E','W')
    for each cell.
    """
    if seed is not None:
        random.seed(seed)
    grid = [[set() for _ in range(cols)] for _ in range(rows)]
    visited = [[False] * cols for _ in range(rows)]
    stack = [(0, 0)]
    visited[0][0] = True
    dirs = {'N': (0, -1), 'S': (0, 1), 'E': (1, 0), 'W': (-1, 0)}
    opposite = {'N': 'S', 'S': 'N', 'E': 'W', 'W': 'E'}

    while stack:
        cx, cy = stack[-1]
        neighbors = []
        for d, (dx, dy) in dirs.items():
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < cols and 0 <= ny < rows and not visited[ny][nx]:
                neighbors.append((d, nx, ny))
        if neighbors:
            d, nx, ny = random.choice(neighbors)
            grid[cy][cx].add(d)
            grid[ny][nx].add(opposite[d])
            visited[ny][nx] = True
            stack.append((nx, ny))
        else:
            stack.pop()
    return grid


def _generate_maze(difficulty, theme, W, H):
    """Grid-based maze via recursive backtracker — recognizable labyrinth.

    Uses wide corridors (cell-based, no explicit corridor walls) and places
    start at top-left cell, target at bottom-right cell. Open top of
    start cell and bottom of target cell for ball entry/exit.
    """
    walls = []
    ks = []
    margin = 40
    usable_w = W - 2 * margin
    usable_h = H - 2 * margin

    # Fewer, larger cells for physics-friendly corridors
    cols = 3 + difficulty   # 4, 5, 6
    rows = 2 + difficulty   # 3, 4, 5
    cell_w = usable_w / cols
    cell_h = usable_h / rows

    grid = _maze_backtrack(cols, rows)

    # Build walls for each cell edge that is closed
    for row in range(rows):
        for col in range(cols):
            x0 = _snap(margin + col * cell_w)
            y0 = _snap(margin + row * cell_h)
            x1 = _snap(margin + (col + 1) * cell_w)
            y1 = _snap(margin + (row + 1) * cell_h)

            # North wall — leave open for start cell (0,0)
            if 'N' not in grid[row][col] and row == 0:
                if col == 0:
                    continue  # Open top of start cell for ball entry
                walls.append([[x0, y0], [x1, y0]])
            # South wall — leave open for target cell (cols-1, rows-1)
            if 'S' not in grid[row][col]:
                if row == rows - 1 and col == cols - 1:
                    continue  # Open bottom of target cell
                walls.append([[x0, y1], [x1, y1]])
            # West wall
            if 'W' not in grid[row][col] and col == 0:
                walls.append([[x0, y0], [x0, y1]])
            # East wall
            if 'E' not in grid[row][col]:
                walls.append([[x1, y0], [x1, y1]])

    # K-gates at T-junctions and L-bends (routing decision points)
    k_positions = []
    for row in range(rows):
        for col in range(cols):
            openings = grid[row][col]
            if len(openings) >= 3:
                # T-junction or crossroads — prime decision point
                cx = _snap(margin + (col + 0.5) * cell_w)
                cy = _snap(margin + (row + 0.5) * cell_h)
                k_positions.append((cx, cy))
            elif difficulty >= 2 and len(openings) == 2:
                # L-bend at harder difficulties
                if not ({'N', 'S'} <= openings or {'E', 'W'} <= openings):
                    cx = _snap(margin + (col + 0.5) * cell_w)
                    cy = _snap(margin + (row + 0.5) * cell_h)
                    k_positions.append((cx, cy))

    max_ks = min(6, 2 + difficulty)
    if len(k_positions) > max_ks:
        k_positions = random.sample(k_positions, max_ks)
    for kx, ky in k_positions:
        ks.append({
            'center': [kx, ky],
            'angle': random.choice([theme[0], theme[1], 0, math.pi / 2]),
        })

    # Start above top-left cell, target below bottom-right cell
    start_x = _snap(margin + cell_w * 0.5)
    start_y = _snap(margin - 15)
    target_x = _snap(margin + (cols - 0.5) * cell_w)
    target_y = _snap(margin + rows * cell_h + 15)

    return walls, ks, {'template': 'maze', 'symmetry': None,
                       'grid_cols': cols, 'grid_rows': rows,
                       'start': [start_x, start_y],
                       'target': [target_x, target_y]}


def _generate_fractal(difficulty, theme, W, H):
    """Fractal tree: binary branching downward, self-similar structure.

    Ball enters at trunk top, branches spread out downward.
    K-gates at each fork determine which branch the ball takes.
    """
    walls = []
    ks = []
    angle_pos, angle_neg = theme
    channel_w = 42  # corridor width — wider for physics reliability

    max_depth = 1 + difficulty  # 2, 3, 4
    trunk_len = _snap(min(140, (H - 140) / (max_depth + 0.5)))
    min_branch = 55

    leaf_positions = []  # track leaf endpoints for target placement

    def branch(x, y, angle, length, depth):
        """Recursively build branching channels with K-gates at forks."""
        if depth > max_depth or length < min_branch:
            leaf_positions.append((_snap(x), _snap(y)))
            return
        # End point of this branch
        ex = x + length * math.sin(angle)
        ey = y + length * math.cos(angle)

        # Channel walls (two parallel walls offset perpendicular to branch)
        perp = angle + math.pi / 2
        hw = channel_w / 2
        ox, oy = hw * math.sin(perp), hw * math.cos(perp)
        walls.append([[_snap(x - ox), _snap(y - oy)],
                      [_snap(ex - ox), _snap(ey - oy)]])
        walls.append([[_snap(x + ox), _snap(y + oy)],
                      [_snap(ex + ox), _snap(ey + oy)]])

        if depth < max_depth and length * INV_PHI >= min_branch:
            # Fork: place K-gate at bifurcation
            ks.append({
                'center': [_snap(ex), _snap(ey)],
                'angle': random.choice([0, angle_pos, angle_neg]),
            })
            child_len = _snap(max(min_branch, length * INV_PHI))
            spread = abs(angle_pos) * (0.7 + 0.3 * random.random())
            branch(ex, ey, angle - spread, child_len, depth + 1)
            branch(ex, ey, angle + spread, child_len, depth + 1)
        else:
            leaf_positions.append((_snap(ex), _snap(ey)))

    start_x = _snap(W / 2)
    start_y = 45
    branch(start_x, start_y, 0, trunk_len, 0)

    # Target at the lowest rightmost leaf
    if leaf_positions:
        leaf_positions.sort(key=lambda p: (-p[1], p[0]))  # lowest, then rightmost
        target_pos = list(leaf_positions[0])
    else:
        target_pos = [_snap(W * 0.75), _snap(H - 60)]

    return walls, ks, {'template': 'fractal', 'symmetry': 'bilateral',
                       'symmetry_axis': W / 2,
                       'start': [start_x, start_y],
                       'target': target_pos}


def _generate_factory(difficulty, theme, W, H):
    """Factory/industrial: horizontal platforms with angled drop-offs.

    Ball rolls along platforms (gravity + slope), drops off the end,
    K-gate below redirects to next platform going the other way.
    Simple but visually clean factory/conveyor feel.
    """
    walls = []
    ks = []
    angle_pos, angle_neg = theme
    num_platforms = 2 + difficulty  # 3, 4, 5

    shelf_ys = _phi_positions(90, H - 80, num_platforms)

    for i, sy in enumerate(shelf_ys):
        margin = 50
        # Gap alternates left/right
        gap_w = random.randint(55, 75)
        if i % 2 == 0:
            # Shelf with gap on right
            walls.append([[_snap(margin), _snap(sy)],
                          [_snap(W - margin - gap_w), _snap(sy)]])
            # Small bumper at gap edge
            walls.append(_wall_from_center(
                _snap(W - margin - gap_w), _snap(sy - 15), angle_neg, 30))
        else:
            # Shelf with gap on left
            walls.append([[_snap(margin + gap_w), _snap(sy)],
                          [_snap(W - margin), _snap(sy)]])
            walls.append(_wall_from_center(
                _snap(margin + gap_w), _snap(sy - 15), angle_pos, 30))

    # K-gates between shelves — near where ball drops through
    for i in range(len(shelf_ys) - 1):
        mid_y = _snap((shelf_ys[i] + shelf_ys[i + 1]) / 2)
        if i % 2 == 0:
            kx = _snap(W - 50 - 30)
        else:
            kx = _snap(50 + 30)
        ks.append({
            'center': [kx, mid_y],
            'angle': random.choice([angle_pos, angle_neg, 0]),
        })

    # Start on the first shelf (ball lands and rolls to gap)
    start_x = _snap(W / 2)
    start_y = _snap(40)
    if (num_platforms - 1) % 2 == 0:
        target_x = _snap(W - 60)
    else:
        target_x = _snap(60)
    target_y = _snap(shelf_ys[-1] + 40)

    return walls, ks, {'template': 'factory', 'symmetry': None,
                       'start': [start_x, start_y],
                       'target': [target_x, target_y]}


def _generate_house(difficulty, theme, W, H):
    """House cross-section: roof, floors, rooms, doorways."""
    walls = []
    ks = []
    angle_pos, angle_neg = theme

    # House boundaries
    left_x = _snap(100)
    right_x = _snap(W - 100)
    house_w = right_x - left_x
    roof_apex_y = _snap(70)
    roof_base_y = _snap(140)
    floor_bottom = _snap(H - 50)

    # Roof: two angled walls meeting at apex
    apex_x = _snap(left_x + house_w / 2)
    chimney_half = 25  # chimney opening half-width
    # Left roof slope (apex to left eave), with chimney gap
    walls.append([[left_x, roof_base_y],
                  [_snap(apex_x - chimney_half), _snap(roof_apex_y + 10)]])
    # Right roof slope
    walls.append([[_snap(apex_x + chimney_half), _snap(roof_apex_y + 10)],
                  [right_x, roof_base_y]])

    # Outer walls (left and right, from roof base to bottom)
    walls.append([[left_x, roof_base_y], [left_x, floor_bottom]])
    walls.append([[right_x, roof_base_y], [right_x, floor_bottom]])

    # Floors
    num_floors = 1 + difficulty  # 2, 3, 4
    floor_ys = _phi_positions(roof_base_y + 30, floor_bottom - 30, num_floors)

    for fi, fy in enumerate(floor_ys):
        # Stairwell position alternates left/right
        if fi % 2 == 0:
            stair_x = _snap(right_x - 70)
            stair_w = 55
        else:
            stair_x = _snap(left_x + 15)
            stair_w = 55

        # Floor with stairwell gap
        if stair_x > left_x + 20:
            walls.append([[left_x, _snap(fy)],
                          [_snap(stair_x), _snap(fy)]])
        if stair_x + stair_w < right_x - 20:
            walls.append([[_snap(stair_x + stair_w), _snap(fy)],
                          [right_x, _snap(fy)]])

        # Room dividers (vertical walls with doorway gaps)
        num_rooms = 1 + (difficulty + 1) // 2  # 1-2 dividers
        room_xs = _phi_positions(left_x + 40, right_x - 40, num_rooms)
        for rx in room_xs:
            # Skip if too close to stairwell
            if abs(rx - stair_x) < 70:
                continue
            # Determine floor above and below
            fy_top = floor_ys[fi - 1] if fi > 0 else roof_base_y
            door_h = 50  # doorway height at bottom of wall
            if fy - fy_top > door_h + 30:
                walls.append([[_snap(rx), _snap(fy_top)],
                              [_snap(rx), _snap(fy - door_h)]])

        # K-gate at stairwell entrance
        ks.append({
            'center': [_snap(stair_x + stair_w / 2), _snap(fy - 30)],
            'angle': random.choice([0, angle_pos, angle_neg]),
        })

    # K-gate inside chimney
    ks.append({
        'center': [apex_x, _snap(roof_apex_y + 35)],
        'angle': random.choice([angle_pos, angle_neg]),
    })

    # Start at chimney top, target at ground floor
    start = [apex_x, _snap(roof_apex_y - 15)]
    target = [_snap(right_x - 50), _snap(floor_bottom - 15)]

    return walls, ks, {'template': 'house', 'symmetry': 'bilateral',
                       'symmetry_axis': apex_x,
                       'start': start, 'target': target}


def _generate_diamond(difficulty, theme, W, H):
    """Concentric diamond outlines with gaps — geometric crystal.

    Each diamond layer has a gap on the upper edge (for ball entry from above)
    and a gap on the lower edge (for exit downward). K-gates at each gap.
    Ball navigates from outside top to inside bottom.
    """
    walls = []
    ks = []
    cx, cy = _snap(W / 2), _snap(H / 2)
    num_layers = 1 + difficulty  # 2, 3, 4

    max_r = min(cx - 60, cy - 60)
    radii = []
    r = max_r
    for _ in range(num_layers):
        radii.append(r)
        r = _snap(max(50, r * INV_PHI))

    for li, radius in enumerate(radii):
        # Diamond vertices: top, right, bottom, left
        verts = [
            [cx, _snap(cy - radius)],          # 0: top
            [_snap(cx + radius), cy],           # 1: right
            [cx, _snap(cy + radius)],           # 2: bottom
            [_snap(cx - radius), cy],           # 3: left
        ]

        # Always gap on upper-left edge (0→1 direction) for ball entry
        # and lower-right edge (2→3 direction) for exit toward next layer
        gap_edges = [0]  # top-right edge: top to right vertex
        if difficulty >= 1:
            gap_edges.append(2)  # bottom-left edge: bottom to left vertex

        for ei in range(4):
            p1 = verts[ei]
            p2 = verts[(ei + 1) % 4]

            if ei in gap_edges:
                gap_size = max(45, radius * 0.3)
                edge_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                if edge_len < gap_size + 20:
                    continue  # edge too short for a gap
                mid_t = 0.5
                half_gap_t = gap_size / (2 * edge_len)
                gs = max(0.1, mid_t - half_gap_t)
                ge = min(0.9, mid_t + half_gap_t)

                gp1 = [_snap(p1[0] + (p2[0] - p1[0]) * gs),
                        _snap(p1[1] + (p2[1] - p1[1]) * gs)]
                gp2 = [_snap(p1[0] + (p2[0] - p1[0]) * ge),
                        _snap(p1[1] + (p2[1] - p1[1]) * ge)]

                walls.append([p1, gp1])
                walls.append([gp2, p2])

                # K-gate at gap center
                gap_cx = (gp1[0] + gp2[0]) / 2
                gap_cy = (gp1[1] + gp2[1]) / 2
                ks.append({
                    'center': [_snap(gap_cx), _snap(gap_cy)],
                    'angle': random.choice([theme[0], theme[1], 0]),
                })
            else:
                walls.append([p1, p2])

    # Start above the top vertex, target below the bottom
    top_r = radii[0]
    start = [cx, _snap(cy - top_r - 20)]
    target = [cx, _snap(cy + top_r + 20)]

    return walls, ks, {'template': 'diamond', 'symmetry': 'bilateral',
                       'symmetry_axis': cx,
                       'start': start, 'target': target}


def _generate_spiral(difficulty, theme, W, H):
    """Concentric rings with gaps — ball spirals inward/downward."""
    walls = []
    ks = []
    # Center in upper portion so gravity helps ball flow down through rings
    cx, cy = _snap(W / 2), _snap(H * 0.4)
    num_rings = 2 + difficulty  # 3, 4, 5

    max_r = min(cx - 60, H - cy - 60, cy - 40)
    ring_radii = _phi_positions(max_r * 0.3, max_r, num_rings)
    ring_radii.sort(reverse=True)  # outermost first

    segments_per_ring = 8 + difficulty * 2  # 10, 12, 14

    for ri, radius in enumerate(ring_radii):
        # Gap angle rotates ~90° per ring
        gap_angle = (ri * math.pi / 2) + random.uniform(-0.2, 0.2)
        gap_idx = int((gap_angle / (2 * math.pi)) * segments_per_ring) % segments_per_ring

        for si in range(segments_per_ring):
            if si == gap_idx:
                # This is the gap — place K-gate here
                seg_angle = 2 * math.pi * si / segments_per_ring
                gx = _snap(cx + radius * math.cos(seg_angle + math.pi / segments_per_ring))
                gy = _snap(cy + radius * math.sin(seg_angle + math.pi / segments_per_ring))
                ks.append({
                    'center': [gx, gy],
                    'angle': random.choice([theme[0], theme[1], 0]),
                })
                continue

            # Wall segment (chord of the ring)
            a1 = 2 * math.pi * si / segments_per_ring
            a2 = 2 * math.pi * (si + 1) / segments_per_ring
            x1 = _snap(cx + radius * math.cos(a1))
            y1 = _snap(cy + radius * math.sin(a1))
            x2 = _snap(cx + radius * math.cos(a2))
            y2 = _snap(cy + radius * math.sin(a2))
            walls.append([[x1, y1], [x2, y2]])

        # Radial guide wall between this ring and next inner ring
        if ri < len(ring_radii) - 1:
            inner_r = ring_radii[ri + 1]
            guide_angle = gap_angle + math.pi  # opposite side from gap
            gx1 = _snap(cx + radius * 0.95 * math.cos(guide_angle))
            gy1 = _snap(cy + radius * 0.95 * math.sin(guide_angle))
            gx2 = _snap(cx + inner_r * 1.05 * math.cos(guide_angle))
            gy2 = _snap(cy + inner_r * 1.05 * math.sin(guide_angle))
            walls.append([[gx1, gy1], [gx2, gy2]])

    # Start above outermost ring, target near center
    outer_r = ring_radii[0] if ring_radii else 100
    start = [cx, _snap(cy - outer_r - 25)]
    target = [cx, _snap(cy + 20)]

    return walls, ks, {'template': 'spiral', 'symmetry': None,
                       'start': start, 'target': target}


def generate_aesthetic_course(seed=None, template=None, difficulty=1):
    """Generate a visually coherent course using golden ratio and theme angles.

    Args:
        seed: Random seed for reproducibility.
        template: One of TEMPLATES list (zigzag, symmetric, pinball, cascade,
                  maze, fractal, factory, house, diamond, spiral).
                  None picks randomly.
        difficulty: 1-3 controls complexity.

    Returns:
        Course dict with _aesthetic metadata for mutation preservation.
    """
    if seed is not None:
        random.seed(seed)

    W, H = PLAYFIELD_W, PLAYFIELD_H

    if template is None:
        template = random.choice(TEMPLATES)

    # Pick a theme angle set
    theme_name = random.choice(list(THEME_ANGLE_SETS.keys()))
    theme = THEME_ANGLE_SETS[theme_name]

    # Boundary walls (left, right, bottom)
    boundary = [
        [[0, 0], [0, H]],
        [[W, 0], [W, H]],
        [[0, H], [W, H]],
    ]

    # Generate template-specific geometry
    generators = {
        'zigzag': _generate_zigzag,
        'symmetric': _generate_symmetric,
        'pinball': _generate_pinball,
        'cascade': _generate_cascade,
        'maze': _generate_maze,
        'fractal': _generate_fractal,
        'factory': _generate_factory,
        'house': _generate_house,
        'diamond': _generate_diamond,
        'spiral': _generate_spiral,
    }
    gen_fn = generators.get(template, _generate_zigzag)
    interior_walls, ks, meta = gen_fn(difficulty, theme, W, H)

    # Start and target: use template suggestions or defaults
    start = meta.get('start', [_snap(random.randint(60, 150)),
                                _snap(random.randint(30, 60))])
    tgt_default = [_snap(random.randint(600, 740)),
                   _snap(random.randint(500, 560))]
    target_pos = meta.get('target', tgt_default)
    target_x, target_y = target_pos[0], target_pos[1]

    # Ensure at least 2 K-gates
    while len(ks) < 2:
        ks.append({
            'center': [_snap(random.uniform(150, 650)),
                       _snap(random.uniform(150, 450))],
            'angle': random.choice([theme[0], theme[1], 0]),
        })

    course = {
        'walls': boundary + interior_walls,
        'ks': ks,
        'start': start,
        'target': {'pos': [target_x, target_y], 'r': 25},
        'name': f'Aesthetic {template} {seed}',
        '_aesthetic': {
            'template': template,
            'theme_angles': theme,
            'symmetry': meta.get('symmetry'),
            'symmetry_axis': meta.get('symmetry_axis'),
        },
    }

    return course


def validate_course(course):
    """Basic validation: has enough structure to be playable."""
    if len(course['walls']) < 4:
        return False
    if len(course['ks']) < 1:
        return False
    return True


def generate_batch(count=50, difficulty_range=(1, 3), slope=None,
                   gap_width_range=(50, 80), physics_overrides=None,
                   component_ratio=0.5):
    """Generate a batch of validated courses with optional physics config.

    component_ratio controls fraction using component-based generation.
    """
    courses = []
    seed = 0
    while len(courses) < count:
        diff = (random.randint(*difficulty_range)
                if difficulty_range[0] != difficulty_range[1]
                else difficulty_range[0])
        if random.random() < component_ratio:
            course = generate_component_course(seed=seed, difficulty=diff)
        else:
            course = generate_course(seed=seed, difficulty=diff,
                                     slope=slope, gap_width_range=gap_width_range)
        if validate_course(course):
            if physics_overrides:
                course['physics'] = physics_overrides
            courses.append(course)
        seed += 1
    return courses


def parse_range(s):
    """Parse 'min-max' string into (int, int) tuple."""
    parts = s.split('-')
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    return (int(parts[0]), int(parts[0]))


if __name__ == '__main__':
    p = argparse.ArgumentParser(
        description='Generate K-Maze courses with tunable parameters.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python3 maze_gen.py                             # 50 mixed-difficulty courses
  python3 maze_gen.py -n 10 -d 1 --slope 0.15    # 10 easy, steep slope
  python3 maze_gen.py --k-bounce 1.3 --gravity 250  # floaty + bouncy K-gates
  python3 maze_gen.py --gap-width 40-60 -d 3      # narrow gaps, hard""")

    # Maze structure
    p.add_argument('-n', '--count', type=int, default=50,
                   help='number of courses to generate (default: 50)')
    p.add_argument('-d', '--difficulty', default='mixed',
                   help='difficulty 1-3 or "mixed" for random (default: mixed)')
    p.add_argument('--slope', type=float, default=None,
                   help='shelf slope factor, e.g. 0.08 (default: random 0.04-0.10)')
    p.add_argument('--gap-width', default='50-80',
                   help='gap width range as min-max, e.g. 60-90 (default: 50-80)')
    p.add_argument('-o', '--output', default='maze_courses.json',
                   help='output filename (default: maze_courses.json)')

    # Physics overrides (embedded in course JSON)
    p.add_argument('--k-bounce', type=float, default=K_RESTITUTION,
                   help=f'K-gate restitution/bounciness (default: {K_RESTITUTION})')
    p.add_argument('--wall-bounce', type=float, default=RESTITUTION,
                   help=f'wall restitution (default: {RESTITUTION})')
    p.add_argument('--gravity', type=float, default=400.0,
                   help='gravity strength in px/s^2 (default: 400)')
    p.add_argument('--drag', type=float, default=DRAG,
                   help=f'air drag factor per frame (default: {DRAG})')
    p.add_argument('--component-ratio', type=float, default=0.5,
                   help='fraction of courses using component-based generation (default: 0.5)')

    args = p.parse_args()

    # Parse difficulty
    if args.difficulty == 'mixed':
        diff_range = (1, 3)
    else:
        d = int(args.difficulty)
        diff_range = (d, d)

    gap_range = parse_range(args.gap_width)

    # Build physics overrides dict
    physics = {
        'k_restitution': args.k_bounce,
        'restitution': args.wall_bounce,
        'gravity': args.gravity,
        'drag': args.drag,
    }

    courses = generate_batch(
        count=args.count,
        difficulty_range=diff_range,
        slope=args.slope,
        gap_width_range=gap_range,
        physics_overrides=physics,
        component_ratio=args.component_ratio,
    )

    with open(args.output, 'w') as f:
        json.dump(courses, f, indent=2)

    # Summary
    print(f"Generated {len(courses)} courses -> {args.output}")
    print(f"  difficulty: {args.difficulty}  slope: {args.slope or 'random 0.04-0.10'}  gaps: {args.gap_width}")
    print(f"  component_ratio: {args.component_ratio}")
    print(f"  physics: gravity={args.gravity}  drag={args.drag}  wall_bounce={args.wall_bounce}  k_bounce={args.k_bounce}")
