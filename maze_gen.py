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

TEMPLATES = ['zigzag', 'symmetric', 'pinball', 'cascade']


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

    return walls, ks, {'template': 'zigzag', 'symmetry': None}


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

    return walls, ks, {'template': 'symmetric', 'symmetry': 'bilateral',
                       'symmetry_axis': axis}


def _generate_pinball(difficulty, theme, W, H):
    """Pinball machine: horizontal shelves with symmetric V-deflectors."""
    walls = []
    ks = []
    angle_pos, angle_neg = theme
    num_rows = 2 + difficulty  # 3-5

    row_ys = _phi_positions(90, H - 70, num_rows)
    deflector_len = random.randint(60, 90)

    for i, ry in enumerate(row_ys):
        # Full-width horizontal shelf with 1-2 gaps
        margin = 30
        num_gaps = 1 + (1 if difficulty >= 2 and i % 2 == 0 else 0)

        if num_gaps == 1:
            # Single gap at phi position
            gap_x = _snap(margin + (W - 2 * margin) *
                          (INV_PHI if i % 2 == 0 else 1 - INV_PHI))
            gap_w = random.randint(50, 65)

            if gap_x - gap_w / 2 > margin + 20:
                walls.append([[_snap(margin), _snap(ry)],
                              [_snap(gap_x - gap_w / 2), _snap(ry)]])
            if gap_x + gap_w / 2 < W - margin - 20:
                walls.append([[_snap(gap_x + gap_w / 2), _snap(ry)],
                              [_snap(W - margin), _snap(ry)]])

            # V-deflector above gap: two walls at ±theme angle
            vx = gap_x
            vy = _snap(ry - 35)
            walls.append(_wall_from_center(
                _snap(vx - deflector_len * 0.3), vy, angle_pos, deflector_len * 0.6))
            walls.append(_wall_from_center(
                _snap(vx + deflector_len * 0.3), vy, angle_neg, deflector_len * 0.6))

            # K-gate at V-tip
            ks.append({
                'center': [_snap(vx), _snap(vy - 15)],
                'angle': random.choice([0, angle_pos, angle_neg]),
            })
        else:
            # Two gaps
            gap1_x = _snap(margin + (W - 2 * margin) * 0.3)
            gap2_x = _snap(margin + (W - 2 * margin) * 0.7)
            gap_w = random.randint(45, 55)

            walls.append([[_snap(margin), _snap(ry)],
                          [_snap(gap1_x - gap_w / 2), _snap(ry)]])
            walls.append([[_snap(gap1_x + gap_w / 2), _snap(ry)],
                          [_snap(gap2_x - gap_w / 2), _snap(ry)]])
            walls.append([[_snap(gap2_x + gap_w / 2), _snap(ry)],
                          [_snap(W - margin), _snap(ry)]])

            for gx in [gap1_x, gap2_x]:
                vy = _snap(ry - 30)
                walls.append(_wall_from_center(
                    _snap(gx - deflector_len * 0.25), vy,
                    angle_pos, deflector_len * 0.5))
                walls.append(_wall_from_center(
                    _snap(gx + deflector_len * 0.25), vy,
                    angle_neg, deflector_len * 0.5))
                ks.append({
                    'center': [_snap(gx), _snap(vy - 12)],
                    'angle': random.choice([0, angle_pos, angle_neg]),
                })

    return walls, ks, {'template': 'pinball', 'symmetry': None}


def _generate_cascade(difficulty, theme, W, H):
    """Cascading platforms: staircase with golden ratio width reduction."""
    walls = []
    ks = []
    angle_pos, angle_neg = theme
    num_platforms = 3 + difficulty  # 4-6

    plat_ys = _phi_positions(70, H - 70, num_platforms)

    # Each platform shorter than the last by INV_PHI
    max_w = W - 100
    plat_widths = []
    w = max_w
    for _ in range(num_platforms):
        plat_widths.append(_snap(max(80, w)))
        w *= INV_PHI

    for i, (py, pw) in enumerate(zip(plat_ys, plat_widths)):
        # Alternate left/right alignment
        if i % 2 == 0:
            px = _snap(50 + (W - 100 - pw) * 0.2)  # left-biased
        else:
            px = _snap(50 + (W - 100 - pw) * 0.8)  # right-biased

        # Horizontal platform
        walls.append([[_snap(px), _snap(py)],
                      [_snap(px + pw), _snap(py)]])

        # Small angled lip at the end to guide the ball
        lip_x = px + pw if i % 2 == 0 else px
        lip_dir = angle_neg if i % 2 == 0 else angle_pos
        walls.append(_wall_from_center(
            _snap(lip_x), _snap(py - 15), lip_dir, 40))

        # K-gate centered on platform
        ks.append({
            'center': [_snap(px + pw / 2), _snap(py - 30)],
            'angle': random.choice([0, angle_pos, angle_neg]),
        })

    # Extra connecting diagonal between platforms for harder levels
    if difficulty >= 2:
        for i in range(min(2, num_platforms - 1)):
            mid_y = (plat_ys[i] + plat_ys[i + 1]) / 2
            mid_x = W / 2
            conn_angle = angle_pos if i % 2 == 0 else angle_neg
            walls.append(_wall_from_center(
                _snap(mid_x), _snap(mid_y), conn_angle, 100))

    return walls, ks, {'template': 'cascade', 'symmetry': None}


def generate_aesthetic_course(seed=None, template=None, difficulty=1):
    """Generate a visually coherent course using golden ratio and theme angles.

    Args:
        seed: Random seed for reproducibility.
        template: One of 'zigzag', 'symmetric', 'pinball', 'cascade'.
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
    }
    gen_fn = generators.get(template, _generate_zigzag)
    interior_walls, ks, meta = gen_fn(difficulty, theme, W, H)

    # Start: top-left region
    start = [_snap(random.randint(60, 150)), _snap(random.randint(30, 60))]

    # Target: bottom-right region
    target_x = _snap(random.randint(600, 740))
    target_y = _snap(random.randint(500, 560))

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
