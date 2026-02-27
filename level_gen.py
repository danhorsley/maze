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


def crossover(p1, p2):
    """Crossover preserving boundary walls."""
    child = copy.deepcopy(p1)
    # Keep boundary walls from p1 (first 3 entries)
    boundary = child['walls'][:3]
    interior_1 = child['walls'][3:]
    interior_2 = p2['walls'][3:]

    mid = len(interior_1) // 2
    child_interior = interior_1[:mid] + copy.deepcopy(interior_2[mid:])
    child['walls'] = boundary + child_interior

    # Crossover K shapes
    mid_k = len(child['ks']) // 2
    child['ks'] = child['ks'][:mid_k] + copy.deepcopy(p2['ks'][mid_k:])

    return child


def mutate(child, mut_rate=0.3):
    """Mutate wall positions, K positions/angles. Can add/remove elements."""
    for wall in child['walls'][3:]:  # Skip boundary walls
        if random.random() < mut_rate:
            wall[0][0] += random.gauss(0, 50)
            wall[0][1] += random.gauss(0, 50)
            wall[1][0] += random.gauss(0, 50)
            wall[1][1] += random.gauss(0, 50)
            # Clamp to playfield
            for pt in wall:
                pt[0] = max(10, min(PLAYFIELD_W - 10, pt[0]))
                pt[1] = max(10, min(PLAYFIELD_H - 10, pt[1]))

    for k in child['ks']:
        if random.random() < mut_rate:
            k['center'][0] += random.gauss(0, 40)
            k['center'][1] += random.gauss(0, 40)
            k['angle'] += random.gauss(0, 0.5)
            k['center'][0] = max(60, min(PLAYFIELD_W - 60, k['center'][0]))
            k['center'][1] = max(60, min(PLAYFIELD_H - 60, k['center'][1]))

    # Occasionally add/remove an interior wall
    if random.random() < mut_rate * 0.3 and len(child['walls']) > 5:
        idx = random.randint(3, len(child['walls']) - 1)
        child['walls'].pop(idx)
    if random.random() < mut_rate * 0.3:
        x1 = random.uniform(50, 750)
        y1 = random.uniform(50, 550)
        child['walls'].append([[x1, y1], [x1 + random.uniform(-150, 150), y1 + random.uniform(-150, 150)]])

    # Occasionally add/remove a K shape
    if random.random() < mut_rate * 0.2 and len(child['ks']) > 1:
        child['ks'].pop(random.randint(0, len(child['ks']) - 1))
    if random.random() < mut_rate * 0.2:
        cx = random.uniform(100, 700)
        cy = random.uniform(100, 500)
        child['ks'].append({'center': [cx, cy], 'angle': random.uniform(0, math.pi * 2)})

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
