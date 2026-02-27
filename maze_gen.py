"""Platform-shelf level generator for K-Maze.

Generates mazes suited to ball-physics gameplay: horizontal shelves with gaps
that balls fall through, K shapes at strategic deflection points, and optional
vertical/diagonal walls for variety.
"""
import random
import math
import json
from physics import PLAYFIELD_W, PLAYFIELD_H


def generate_course(seed=None, difficulty=1):
    """Generate a single playable K-Maze course.

    difficulty: 1-3, controls shelf count, gap count, K placement.
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

    # Generate shelves with gaps
    # Shelves slope down left-to-right so the ball naturally rolls toward the target
    slope = random.uniform(0.04, 0.10)  # Y drop per X pixel (gentle slope)
    gap_positions = []

    for shelf_idx, sy in enumerate(shelf_ys):
        num_gaps = random.randint(1, 1 + difficulty)
        shelf_left = random.randint(20, 60)
        shelf_right = PLAYFIELD_W - random.randint(20, 60)
        gap_width = random.randint(50, 80)

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
        def shelf_y(x):
            return int(sy + (x - shelf_left) * slope)

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


def validate_course(course):
    """Basic validation: has enough structure to be playable."""
    if len(course['walls']) < 4:
        return False
    if len(course['ks']) < 1:
        return False
    return True


def generate_batch(count=50, difficulty_range=(1, 3)):
    """Generate a batch of validated courses."""
    courses = []
    seed = 0
    while len(courses) < count:
        diff = random.randint(*difficulty_range)
        course = generate_course(seed=seed, difficulty=diff)
        if validate_course(course):
            courses.append(course)
        seed += 1
    return courses


if __name__ == '__main__':
    courses = generate_batch(50)
    with open('maze_courses.json', 'w') as f:
        json.dump(courses, f, indent=2)
    print(f"Generated {len(courses)} courses! Load in editor.")
