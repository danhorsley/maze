"""Genetic algorithm level generator for K-Maze.

Evolves levels using canonical physics from physics.py. Can seed initial
population from maze_gen for structural diversity.
"""
import random
import math
import json
import copy

from physics import (
    K_REL_POINTS, GRAVITY, DRAG, BALL_R, DT, RESTITUTION,
    PLAYFIELD_W, PLAYFIELD_H,
    rotate_points, reflect_ball_over_line, simulate_ball,
)
from maze_gen import generate_course


def simulate_level(level, max_balls=3, trials=5):
    """Evaluate a level's fitness using canonical physics.

    Returns fitness score (higher = better level).
    """
    walls = level['walls']
    ks = level['ks']
    start = level['start']
    tgt = level['target']
    target_pos = tgt['pos'] if isinstance(tgt, dict) else tgt[:2]
    target_r = tgt.get('r', 25) if isinstance(tgt, dict) else (tgt[2] if len(tgt) >= 3 else 25)

    best_fitness = 0

    for _ in range(trials):
        # Randomize K angles per trial
        ks_copy = [{'center': k['center'][:], 'angle': random.uniform(0, math.pi * 2)} for k in ks]
        min_dist = float('inf')
        total_k_hits = 0

        for balls_used in range(1, max_balls + 1):
            pos = start[:]
            vel = [0.0, 0.0]

            final_pos, final_vel, steps, wall_hits, k_hits, trajectory = \
                simulate_ball(pos, vel, walls, ks_copy, max_steps=600)

            total_k_hits += k_hits

            # Check trajectory for target proximity
            hit_target = False
            for tp in trajectory:
                cur_dist = math.hypot(tp[0] - target_pos[0], tp[1] - target_pos[1])
                min_dist = min(min_dist, cur_dist)
                if cur_dist < target_r + BALL_R:
                    fitness = 1.0 / balls_used + 0.3 * (total_k_hits / max(1, len(ks)))
                    best_fitness = max(best_fitness, fitness)
                    hit_target = True
                    break
            if hit_target:
                break

        # Partial credit if no win
        if best_fitness == 0:
            partial = (600 - min(min_dist, 600)) / 600 * 0.2 + steps / 600 * 0.1
            best_fitness = max(best_fitness, partial)

    return best_fitness / trials


def rand_level_structured():
    """Seed from maze_gen for structural diversity."""
    return generate_course(seed=random.randint(0, 100000), difficulty=random.randint(1, 3))


def rand_level_random():
    """Purely random level (kept for genetic diversity)."""
    base_walls = [[[0, 0], [0, 600]], [[800, 0], [800, 600]], [[0, 600], [800, 600]]]
    extra_walls = []
    for _ in range(random.randint(3, 5)):
        x1, y1 = random.uniform(50, 750), random.uniform(50, 550)
        x2 = x1 + random.uniform(-150, 150)
        y2 = y1 + random.uniform(-150, 150)
        extra_walls.append([[x1, y1], [x2, y2]])
    walls = base_walls + extra_walls

    ks = []
    for _ in range(random.randint(2, 4)):
        cx = random.uniform(150, 650)
        cy = random.uniform(100, 500)
        while math.hypot(cx - 90, cy - 60) < 100 or math.hypot(cx - 680, cy - 530) < 100:
            cx, cy = random.uniform(150, 650), random.uniform(100, 500)
        ks.append({'center': [cx, cy], 'angle': random.uniform(0, math.pi * 2)})

    return {
        'walls': walls, 'ks': ks,
        'start': [90, 60],
        'target': {'pos': [680, 530], 'r': 25},
        'name': 'Random',
    }


# Canonical angles for new walls when no theme is available
_CANONICAL_ANGLES = [0, math.pi / 6, -math.pi / 6,
                     math.pi / 4, -math.pi / 4,
                     math.pi / 3, -math.pi / 3,
                     math.pi / 2]


def _snap_angle(angle, theme_angles):
    """Snap angle to the nearest theme angle (or horizontal/vertical)."""
    candidates = list(theme_angles) + [0, math.pi / 2, -math.pi / 2]
    return min(candidates, key=lambda a: abs(angle - a))


def crossover(p1, p2):
    """Spatial crossover: split by Y coordinate to preserve structural coherence."""
    child = copy.deepcopy(p1)
    boundary = child['walls'][:3]

    # Random Y split in the middle third of the playfield
    split_y = random.uniform(PLAYFIELD_H * 0.3, PLAYFIELD_H * 0.7)

    def wall_center_y(w):
        return (w[0][1] + w[1][1]) / 2

    # Upper walls from p1, lower walls from p2
    interior = [copy.deepcopy(w) for w in p1['walls'][3:]
                if wall_center_y(w) < split_y]
    interior += [copy.deepcopy(w) for w in p2['walls'][3:]
                 if wall_center_y(w) >= split_y]
    child['walls'] = boundary + interior

    # K shapes: same spatial split
    child_ks = [copy.deepcopy(k) for k in p1['ks']
                if k['center'][1] < split_y]
    child_ks += [copy.deepcopy(k) for k in p2['ks']
                 if k['center'][1] >= split_y]

    # Ensure at least 1 K shape
    if not child_ks:
        child_ks = copy.deepcopy(p1['ks'][:1]) or copy.deepcopy(p2['ks'][:1])

    child['ks'] = child_ks

    # Preserve aesthetic metadata if both parents share the same template
    a1 = p1.get('_aesthetic', {})
    a2 = p2.get('_aesthetic', {})
    if a1.get('template') and a1.get('template') == a2.get('template'):
        child['_aesthetic'] = {
            'template': a1['template'],
            'theme_angles': a1.get('theme_angles', a2.get('theme_angles')),
            'symmetry': a1.get('symmetry'),
            'symmetry_axis': a1.get('symmetry_axis'),
        }
    elif '_aesthetic' in child:
        del child['_aesthetic']

    return child


def mutate(child, mut_rate=0.3, temperature=1.0):
    """Structure-preserving mutation using rigid-body wall perturbation.

    Walls are translated as rigid segments (preserving angle) rather than
    having each endpoint perturbed independently. If the course has
    _aesthetic.theme_angles, wall angles are snapped to the nearest theme
    angle 80% of the time, keeping visual coherence through evolution.

    temperature: 0.0-1.0 scales perturbation magnitude (simulated annealing).
        1.0 = full exploration (early generations)
        0.2 = fine tuning (late generations)
    """
    wall_sigma = 50 * temperature
    k_pos_sigma = 40 * temperature
    k_angle_sigma = 0.5 * temperature
    add_remove_rate = mut_rate * 0.3 * temperature

    aesthetic = child.get('_aesthetic', {})
    theme = aesthetic.get('theme_angles')

    PW, PH = PLAYFIELD_W, PLAYFIELD_H

    # Rigid-body wall mutation: translate center, optionally snap angle
    for wall in child['walls'][3:]:  # Skip boundary walls
        if random.random() < mut_rate:
            # Decompose into center, angle, length
            cx = (wall[0][0] + wall[1][0]) / 2
            cy = (wall[0][1] + wall[1][1]) / 2
            dx = wall[1][0] - wall[0][0]
            dy = wall[1][1] - wall[0][1]
            length = math.hypot(dx, dy)
            if length < 1:
                continue
            angle = math.atan2(dy, dx)

            # Translate center (preserves angle)
            cx += random.gauss(0, wall_sigma * 0.7)
            cy += random.gauss(0, wall_sigma * 0.7)

            # Perturb length slightly
            length *= 1.0 + random.gauss(0, 0.1 * temperature)
            length = max(20, min(300, length))

            # Angle: snap to theme if available (80% chance), else small perturbation
            if theme and random.random() < 0.8:
                angle = _snap_angle(angle, theme)
            else:
                angle += random.gauss(0, 0.15 * temperature)

            # Reconstruct endpoints
            half_dx = length / 2 * math.cos(angle)
            half_dy = length / 2 * math.sin(angle)
            wall[0] = [max(10, min(PW - 10, cx - half_dx)),
                       max(10, min(PH - 10, cy - half_dy))]
            wall[1] = [max(10, min(PW - 10, cx + half_dx)),
                       max(10, min(PH - 10, cy + half_dy))]

    # K-gates: smaller position shift (aesthetics), larger angle shift (gameplay)
    for k in child['ks']:
        if random.random() < mut_rate:
            k['center'][0] += random.gauss(0, k_pos_sigma * 0.5)
            k['center'][1] += random.gauss(0, k_pos_sigma * 0.5)
            k['angle'] += random.gauss(0, k_angle_sigma * 1.5)
            k['center'][0] = max(60, min(PW - 60, k['center'][0]))
            k['center'][1] = max(60, min(PH - 60, k['center'][1]))

    # Occasionally add/remove an interior wall (scales with temperature)
    if random.random() < add_remove_rate and len(child['walls']) > 5:
        idx = random.randint(3, len(child['walls']) - 1)
        child['walls'].pop(idx)
    if random.random() < add_remove_rate:
        x1 = random.uniform(50, 750)
        y1 = random.uniform(50, 550)
        # Use theme angles or canonical angles instead of random
        if theme:
            angle = random.choice(list(theme) + [0])
        else:
            angle = random.choice(_CANONICAL_ANGLES)
        length = random.uniform(60, 180)
        x2 = max(10, min(PW - 10, x1 + length * math.cos(angle)))
        y2 = max(10, min(PH - 10, y1 + length * math.sin(angle)))
        child['walls'].append([[x1, y1], [x2, y2]])

    # Occasionally add/remove a K shape (scales with temperature)
    k_add_remove_rate = mut_rate * 0.2 * temperature
    if random.random() < k_add_remove_rate and len(child['ks']) > 1:
        child['ks'].pop(random.randint(0, len(child['ks']) - 1))
    if random.random() < k_add_remove_rate:
        cx = random.uniform(100, 700)
        cy = random.uniform(100, 500)
        # Use theme angle or canonical for new K
        if theme:
            ka = random.choice(list(theme) + [0])
        else:
            ka = random.uniform(0, math.pi * 2)
        child['ks'].append({'center': [cx, cy], 'angle': ka})

    # Symmetry preservation: re-mirror if bilateral
    if aesthetic.get('symmetry') == 'bilateral':
        axis = aesthetic.get('symmetry_axis', PW / 2)
        interior = child['walls'][3:]
        # Find walls on left side and mirror to right
        for wall in interior:
            cx = (wall[0][0] + wall[1][0]) / 2
            if cx < axis - 20:
                # Look for a corresponding right-side wall
                for other in interior:
                    if other is wall:
                        continue
                    ocx = (other[0][0] + other[1][0]) / 2
                    ocy = (other[0][1] + other[1][1]) / 2
                    expected_cx = 2 * axis - cx
                    cy = (wall[0][1] + wall[1][1]) / 2
                    if abs(ocx - expected_cx) < 60 and abs(ocy - cy) < 60:
                        # Re-mirror this wall
                        other[0][0] = 2 * axis - wall[1][0]
                        other[0][1] = wall[1][1]
                        other[1][0] = 2 * axis - wall[0][0]
                        other[1][1] = wall[0][1]
                        break

    return child


if __name__ == '__main__':
    # GA parameters
    POP = 100
    GENS = 500
    MUT_RATE = 0.3
    SAVE_INTERVAL = 50

    # Initialize population: 50% structured, 50% random
    pop = []
    for _ in range(POP // 2):
        pop.append(rand_level_structured())
    for _ in range(POP - len(pop)):
        pop.append(rand_level_random())

    best_ever = []

    for g in range(GENS):
        # Evaluate fitness
        for level in pop:
            level['fitness'] = simulate_level(level)

        scored = sorted(pop, key=lambda l: l['fitness'], reverse=True)
        print(f"Gen {g}: Best {scored[0]['fitness']:.3f}")

        # Track best
        for lvl in scored[:5]:
            if lvl['fitness'] > 0.3:
                best_ever.append(copy.deepcopy(lvl))

        # Save intermediate results
        if (g + 1) % SAVE_INTERVAL == 0 and best_ever:
            # Deduplicate by taking unique top scorers
            best_ever.sort(key=lambda l: l['fitness'], reverse=True)
            intermediate = best_ever[:50]
            for lvl in intermediate:
                lvl.pop('fitness', None)
            with open('auto_levels.json', 'w') as f:
                json.dump(intermediate, f, indent=2)
            print(f"  Saved {len(intermediate)} intermediate levels")

        # Selection: top 25%
        elites = scored[:POP // 4]

        # Generate offspring
        offspring = []
        while len(offspring) < POP - len(elites):
            p1, p2 = random.choices(elites, k=2)
            child = crossover(p1, p2)
            child = mutate(child, MUT_RATE)
            offspring.append(child)

        pop = [copy.deepcopy(e) for e in elites] + offspring

    # Final save
    for level in pop:
        level['fitness'] = simulate_level(level)

    all_levels = pop + best_ever
    all_levels.sort(key=lambda l: l['fitness'], reverse=True)

    # Deduplicate and filter
    goods = []
    seen = set()
    for lvl in all_levels:
        if lvl['fitness'] > 0.3:
            key = str(lvl['walls'][:5])  # rough dedup
            if key not in seen:
                seen.add(key)
                lvl.pop('fitness', None)
                goods.append(lvl)
        if len(goods) >= 50:
            break

    with open('auto_levels.json', 'w') as f:
        json.dump(goods, f, indent=2)
    print(f"Saved {len(goods)} auto-levels!")
