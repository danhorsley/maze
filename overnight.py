"""Overnight batch runner for K-Maze.

Generates, tests, evolves, and ranks courses to find the best 50 by morning.
Combines shelf-based, component-based, and random generation with GA evolution.
Assigns physics wobble to final selections for gameplay variety.

Usage:
    python3 overnight.py                                    # default ~6 hour run
    python3 overnight.py --pool 200 --gens 10 --cycles 3   # shorter ~2 hour run
    python3 overnight.py --resume overnight_progress.json   # resume from checkpoint
    python3 overnight.py -o my_best.json                    # custom output file
"""
import argparse
import copy
import json
import math
import multiprocessing
import os
import random
import time

from physics import PLAYFIELD_W, PLAYFIELD_H, BALL_R
from maze_gen import (generate_course, generate_component_course,
                      generate_aesthetic_course, validate_course, TEMPLATES)
from level_tester import test_course, quick_test
from level_gen import crossover, mutate
from stock_shapes import get_component, translate_component, COMPONENT_REGISTRY


# ─── Defaults ───

DEFAULTS = {
    'pool_size': 300,
    'pop_size': 100,
    'generations': 15,
    'cycles': 5,
    'elite_fraction': 0.25,
    'mutation_rate': 0.3,
    'injection_rate': 0.15,
    'angle_steps': 12,
    'max_combos': 200,
    'max_steps': 350,
    'target_count': 50,
    'save_interval': 5,
}


# ─── Logging ───

_start_time = None


def log(msg):
    elapsed = time.time() - _start_time if _start_time else 0
    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    s = int(elapsed % 60)
    print(f"[{h:02d}:{m:02d}:{s:02d}] {msg}", flush=True)


def log_eta(done, total, phase_start):
    if done <= 0:
        return
    elapsed = time.time() - phase_start
    per_item = elapsed / done
    remaining = per_item * (total - done)
    rm, rs = int(remaining // 60), int(remaining % 60)
    log(f"  ... {done}/{total} done, ~{rm}m{rs:02d}s remaining")


# ─── Parameter Tracker ───

class ParamTracker:
    """Track which generation parameters produce good courses.

    Records (params_dict, score) pairs and computes success rates
    per parameter value to bias future generation.
    """

    def __init__(self, threshold=0.3):
        self.records = []
        self.threshold = threshold

    def record(self, params, score):
        """Log a generation attempt and its resulting score."""
        self.records.append((params, score))

    def success_rate(self, key, value):
        """Fraction of courses with params[key]==value scoring above threshold."""
        matching = [(p, s) for p, s in self.records if p.get(key) == value]
        if len(matching) < 5:
            return 0.5  # Not enough data — neutral
        return sum(1 for _, s in matching if s > self.threshold) / len(matching)

    def best_values(self, key):
        """Return [(value, success_rate)] sorted by success rate descending."""
        values = set(p.get(key) for p, _ in self.records if key in p)
        rated = [(v, self.success_rate(key, v)) for v in values]
        rated.sort(key=lambda x: x[1], reverse=True)
        return rated

    def suggest_params(self):
        """Return biased parameter distributions based on past success."""
        suggestion = {}
        if len(self.records) < 30:
            return suggestion  # Not enough data yet

        method_rates = self.best_values('method')
        if method_rates:
            total = sum(r for _, r in method_rates)
            if total > 0:
                suggestion['method_weights'] = {
                    m: r / total for m, r in method_rates
                }

        diff_rates = self.best_values('difficulty')
        if diff_rates:
            total = sum(r for _, r in diff_rates)
            if total > 0:
                suggestion['difficulty_weights'] = {
                    d: r / total for d, r in diff_rates
                }

        return suggestion

    def summary(self):
        """Return a human-readable summary for logging."""
        if len(self.records) < 10:
            return f"ParamTracker: {len(self.records)} records (not enough data)"
        lines = [f"ParamTracker: {len(self.records)} records"]
        for key in ('method', 'difficulty'):
            rates = self.best_values(key)
            if rates:
                parts = [f"{v}={r:.0%}" for v, r in rates[:5]]
                lines.append(f"  {key}: {', '.join(parts)}")
        return '\n'.join(lines)


# ─── Aesthetic scoring ───

def _angle_consistency(walls):
    """Score how well walls use a consistent set of angles (0-1)."""
    angles = []
    for wall in walls[3:]:
        dx = wall[1][0] - wall[0][0]
        dy = wall[1][1] - wall[0][1]
        if abs(dx) < 1 and abs(dy) < 1:
            continue
        a = math.atan2(dy, dx) % math.pi  # normalise to [0, π)
        angles.append(a)
    if len(angles) < 2:
        return 0.5

    # Cluster angles with 5-degree tolerance
    tol = math.radians(5)
    angles.sort()
    clusters = [[angles[0]]]
    for a in angles[1:]:
        if a - clusters[-1][0] < tol:
            clusters[-1].append(a)
        else:
            clusters.append([a])
    # Merge wraparound (near 0 and near π)
    if len(clusters) > 1 and (math.pi - clusters[-1][0] + clusters[0][0]) < tol:
        clusters[0].extend(clusters.pop())

    clusters.sort(key=len, reverse=True)
    top2 = sum(len(c) for c in clusters[:2])
    return top2 / len(angles)


def _spacing_regularity(walls):
    """Score how evenly walls are distributed vertically (0-1)."""
    y_centers = sorted((w[0][1] + w[1][1]) / 2 for w in walls[3:])
    if len(y_centers) < 3:
        return 0.5
    gaps = [y_centers[i + 1] - y_centers[i]
            for i in range(len(y_centers) - 1)]
    gaps = [g for g in gaps if g > 5]
    if len(gaps) < 2:
        return 0.5
    mean = sum(gaps) / len(gaps)
    if mean < 1:
        return 0.0
    variance = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    cv = math.sqrt(variance) / mean
    return max(0.0, min(1.0, 1.0 - cv))


def _symmetry_score(walls, axis=None):
    """Score bilateral symmetry around axis (0-1)."""
    if axis is None:
        axis = PLAYFIELD_W / 2
    interior = walls[3:]
    if len(interior) < 2:
        return 0.0
    matched = 0
    for wall in interior:
        cx = (wall[0][0] + wall[1][0]) / 2
        cy = (wall[0][1] + wall[1][1]) / 2
        mirror_cx = 2 * axis - cx
        for other in interior:
            if other is wall:
                continue
            ocx = (other[0][0] + other[1][0]) / 2
            ocy = (other[0][1] + other[1][1]) / 2
            if abs(ocx - mirror_cx) < 50 and abs(ocy - cy) < 50:
                matched += 1
                break
    return matched / len(interior)


def _k_alignment(ks):
    """Score how regularly K-gates are arranged (0-1)."""
    if len(ks) < 2:
        return 0.5
    # Check horizontal or vertical alignment
    xs = [k['center'][0] for k in ks]
    ys = [k['center'][1] for k in ks]

    # X-alignment: fraction with similar x (within 40px of another)
    x_aligned = 0
    for i, x in enumerate(xs):
        for j, x2 in enumerate(xs):
            if i != j and abs(x - x2) < 40:
                x_aligned += 1
                break

    # Y-alignment: similar
    y_aligned = 0
    for i, y in enumerate(ys):
        for j, y2 in enumerate(ys):
            if i != j and abs(y - y2) < 40:
                y_aligned += 1
                break

    return max(x_aligned, y_aligned) / len(ks)


def aesthetic_score(course):
    """Score visual coherence of a course 0.0-1.0.

    Components:
      - Angle consistency (40%): walls use a few consistent angles
      - Spacing regularity (30%): walls evenly distributed vertically
      - Symmetry (20%): bilateral mirror match
      - K-gate alignment (10%): K-gates form a pattern
    """
    walls = course.get('walls', [])
    ks = course.get('ks', [])

    if len(walls) <= 3:
        return 0.0

    sym_axis = course.get('_aesthetic', {}).get('symmetry_axis')

    a_con = _angle_consistency(walls)
    a_spa = _spacing_regularity(walls)
    a_sym = _symmetry_score(walls, sym_axis)
    a_k = _k_alignment(ks)

    return 0.40 * a_con + 0.30 * a_spa + 0.20 * a_sym + 0.10 * a_k


# ─── Gameplay scoring ───

def composite_score(scores, course=None):
    """Score a tested course 0.0-1.0 for gameplay + aesthetic quality."""
    if not scores['solvable']:
        base = 0.05 * max(0, 1.0 - scores['best_min_dist'] / 600)
        # Still give partial aesthetic credit to help the GA learn
        if course is not None:
            base += 0.05 * aesthetic_score(course)
        return base

    s = 0.0

    # K-dependency (40%): courses must use K shapes
    k_dep = scores['k_dependency']
    if k_dep < 0.1:
        s += 0.0
    elif k_dep < 0.3:
        s += 0.15 * (k_dep / 0.3)
    else:
        s += 0.15 + 0.25 * min(1.0, (k_dep - 0.3) / 0.5)

    # Solve rate (25%): sweet spot 0.01-0.05
    sr = scores['solve_rate']
    if sr < 0.005:
        s += 0.10
    elif sr <= 0.05:
        s += 0.25
    elif sr <= 0.20:
        s += 0.20
    else:
        s += 0.10 * max(0, 1.0 - (sr - 0.20) / 0.30)

    # Path length (20%): sweet spot 80-250 steps (1.3-4.2s), zero above 350
    pl = scores['path_length']
    if pl < 40:
        s += 0.03
    elif pl < 80:
        s += 0.03 + 0.07 * ((pl - 40) / 40)
    elif pl <= 250:
        s += 0.20
    elif pl <= 350:
        s += 0.20 * (1.0 - (pl - 250) / 100)
    else:
        s += 0.0  # >350 steps = boring loop, zero credit

    # Bounce variety (10%): mix of wall and K bounces
    wb = scores['wall_bounces']
    kb = scores['k_bounces']
    if wb + kb > 2:
        variety = min(wb, kb) / max(1, max(wb, kb))
        s += 0.10 * min(1.0, variety + 0.3)
    else:
        s += 0.02

    # Solvable bonus (10%)
    s += 0.10

    # Aesthetic bonus (up to 0.20 additional — reduced since templates
    # guarantee aesthetics, freed 5% went to path length)
    if course is not None:
        s += 0.20 * aesthetic_score(course)

    return min(1.0, s)


# ─── Deduplication ───

def course_fingerprint(course):
    """Hashable fingerprint from coarsened wall/K positions."""
    wall_pts = []
    for w in course['walls'][3:]:
        wall_pts.append((
            round(w[0][0] / 40), round(w[0][1] / 40),
            round(w[1][0] / 40), round(w[1][1] / 40),
        ))
    wall_pts.sort()

    k_pts = []
    for k in course['ks']:
        k_pts.append((
            round(k['center'][0] / 40), round(k['center'][1] / 40),
        ))
    k_pts.sort()

    return (tuple(wall_pts), tuple(k_pts))


def deduplicate(courses, max_out=50):
    """Keep top-scoring unique courses."""
    ranked = sorted(courses, key=lambda c: c.get('_score', 0), reverse=True)
    seen = set()
    result = []
    for c in ranked:
        fp = course_fingerprint(c)
        if fp not in seen:
            seen.add(fp)
            result.append(c)
        if len(result) >= max_out:
            break
    return result


# ─── Physics wobble ───

def assign_physics_wobble(course):
    """Assign slightly varied physics for gameplay variety."""
    course['physics'] = {
        'gravity': round(random.uniform(350, 450), 1),
        'drag': round(random.uniform(0.992, 0.998), 4),
        'restitution': round(random.uniform(0.80, 0.90), 3),
        'k_restitution': round(random.uniform(1.00, 1.10), 3),
    }


# ─── Pool generation ───

def rand_level_diverse(seed=None):
    """Random level with embedded stock components for genetic diversity."""
    if seed is not None:
        random.seed(seed)

    walls = [
        [[0, 0], [0, PLAYFIELD_H]],
        [[PLAYFIELD_W, 0], [PLAYFIELD_W, PLAYFIELD_H]],
        [[0, PLAYFIELD_H], [PLAYFIELD_W, PLAYFIELD_H]],
    ]
    ks = []

    # Drop 0-2 stock components at random positions
    comp_names = list(COMPONENT_REGISTRY.keys())
    for _ in range(random.randint(0, 2)):
        comp = get_component(random.choice(comp_names))
        if comp:
            bbox = comp['bbox']
            max_x = PLAYFIELD_W - (bbox[2] - bbox[0]) - 20
            max_y = PLAYFIELD_H - (bbox[3] - bbox[1]) - 20
            if max_x > 20 and max_y > 80:
                placed = translate_component(comp,
                                             random.uniform(20, max_x) - bbox[0],
                                             random.uniform(80, max_y) - bbox[1])
                walls.extend(placed['walls'])
                ks.extend(placed['ks'])

    # Random extra walls
    for _ in range(random.randint(2, 5)):
        x1 = random.uniform(50, 750)
        y1 = random.uniform(80, 550)
        length = random.uniform(60, 200)
        angle = random.uniform(-math.pi / 3, math.pi / 3)
        x2 = max(10, min(PLAYFIELD_W - 10, x1 + length * math.cos(angle)))
        y2 = max(10, min(PLAYFIELD_H - 10, y1 + length * math.sin(angle)))
        walls.append([[x1, y1], [x2, y2]])

    # Random K shapes
    for _ in range(random.randint(2, 4)):
        ks.append({
            'center': [random.uniform(100, 700), random.uniform(100, 500)],
            'angle': random.uniform(0, 2 * math.pi),
        })

    return {
        'walls': walls, 'ks': ks,
        'start': [random.randint(60, 200), random.randint(30, 60)],
        'target': {'pos': [random.randint(600, 740), random.randint(520, 570)], 'r': 25},
        'name': f'Diverse {seed}',
    }


def generate_seed_pool(pool_size, difficulty_range, tracker=None):
    """Generate initial diverse pool, optionally biased by tracker."""
    log(f"Generating seed pool of {pool_size} courses...")
    courses = []

    # Determine method split from tracker or use defaults
    # Aesthetic gets 45% by default — it's the primary method now
    suggestion = tracker.suggest_params() if tracker else {}
    method_weights = suggestion.get('method_weights',
                                     {'aesthetic': 0.45, 'shelf': 0.20,
                                      'component': 0.20, 'diverse': 0.15})

    # Normalise weights to counts
    total_w = sum(method_weights.values())
    method_counts = {m: max(1, int(pool_size * w / total_w))
                     for m, w in method_weights.items()}

    slopes = [None, 0.04, 0.06, 0.08, 0.10, 0.12]
    gap_ranges = [(40, 60), (50, 80), (60, 100), (70, 90)]

    seed_idx = 0

    # Aesthetic courses — golden ratio + theme angles
    for i in range(method_counts.get('aesthetic', 0)):
        diff = random.randint(*difficulty_range)
        template = random.choice(TEMPLATES)
        c = generate_aesthetic_course(seed=seed_idx, template=template,
                                      difficulty=diff)
        if validate_course(c):
            c['_gen_params'] = {'method': 'aesthetic', 'difficulty': diff,
                                'template': template}
            courses.append(c)
        seed_idx += 1

    # Shelf-based courses
    for i in range(method_counts.get('shelf', 0)):
        diff = random.randint(*difficulty_range)
        slope = random.choice(slopes)
        gap_range = random.choice(gap_ranges)
        c = generate_course(seed=seed_idx, difficulty=diff, slope=slope,
                            gap_width_range=gap_range)
        if validate_course(c):
            c['_gen_params'] = {'method': 'shelf', 'difficulty': diff,
                                'slope': slope, 'gap_range': gap_range}
            courses.append(c)
        seed_idx += 1

    # Component-based courses
    for i in range(method_counts.get('component', 0)):
        diff = random.randint(*difficulty_range)
        c = generate_component_course(seed=seed_idx, difficulty=diff)
        if validate_course(c):
            c['_gen_params'] = {'method': 'component', 'difficulty': diff}
            courses.append(c)
        seed_idx += 1

    # Fill remainder with diverse random
    random_target = pool_size - len(courses)
    for i in range(max(0, random_target)):
        c = rand_level_diverse(seed=seed_idx)
        if validate_course(c):
            c['_gen_params'] = {'method': 'diverse', 'difficulty': 0}
            courses.append(c)
        seed_idx += 1

    counts_str = ' '.join(f"{m}={method_counts.get(m, 0)}"
                          for m in ['aesthetic', 'shelf', 'component', 'diverse'])
    log(f"  Generated {len(courses)} valid courses ({counts_str})")
    return courses


# ─── Testing ───

def _score_worker(args):
    """Worker function for multiprocessing. Pre-filters then scores."""
    course, angle_steps, max_combos, max_steps = args

    # Quick pre-filter: 8 random angle probes
    skip, best_dist = quick_test(course, samples=8, max_steps=max_steps)
    if skip:
        scores = {
            'solvable': False, 'solve_rate': 0,
            'best_min_dist': round(best_dist, 1),
            'k_dependency': 0, 'path_length': 0,
            'wall_bounces': 0, 'k_bounces': 0,
        }
        score = composite_score(scores, course=course)
        return scores, score

    # Full test
    scores = test_course(course, angle_steps=angle_steps,
                         max_combos=max_combos, max_steps=max_steps)
    score = composite_score(scores, course=course)
    return scores, score


def score_population(population, angle_steps, max_combos, max_steps=400,
                     label="", workers=None):
    """Test and score all courses. Skips already-scored courses."""
    phase_start = time.time()

    to_score_indices = [i for i, c in enumerate(population) if '_scores' not in c]
    to_score_count = len(to_score_indices)

    if to_score_count == 0:
        elapsed = time.time() - phase_start
        solvable = sum(1 for c in population
                       if c.get('_scores', {}).get('solvable', False))
        avg = sum(c.get('_score', 0) for c in population) / max(1, len(population))
        log(f"  {label}Scored 0 new ({len(population)} total) in {elapsed:.0f}s "
            f"- {solvable} solvable, avg={avg:.3f}")
        return

    work_items = [
        (population[i], angle_steps, max_combos, max_steps)
        for i in to_score_indices
    ]

    scored = 0
    use_parallel = workers != 1 and to_score_count > 1

    if use_parallel:
        try:
            num_workers = workers or os.cpu_count() or 4
            num_workers = min(num_workers, to_score_count)

            with multiprocessing.Pool(processes=num_workers) as pool:
                results = pool.map(_score_worker, work_items)

            for idx, (scores, score) in zip(to_score_indices, results):
                population[idx]['_scores'] = scores
                population[idx]['_score'] = score
            scored = to_score_count

        except Exception as e:
            log(f"  Warning: multiprocessing failed ({e}), falling back to sequential")
            use_parallel = False

    if not use_parallel:
        for i in to_score_indices:
            course = population[i]
            if '_scores' not in course:
                # Quick pre-filter
                skip, best_dist = quick_test(course, samples=8,
                                             max_steps=max_steps)
                if skip:
                    course['_scores'] = {
                        'solvable': False, 'solve_rate': 0,
                        'best_min_dist': round(best_dist, 1),
                        'k_dependency': 0, 'path_length': 0,
                        'wall_bounces': 0, 'k_bounces': 0,
                    }
                    course['_score'] = composite_score(course['_scores'],
                                                       course=course)
                else:
                    scores = test_course(course, angle_steps=angle_steps,
                                         max_combos=max_combos, max_steps=max_steps)
                    course['_scores'] = scores
                    course['_score'] = composite_score(scores, course=course)
                scored += 1

                if scored % 50 == 0 and to_score_count > 50:
                    log_eta(scored, to_score_count, phase_start)

    elapsed = time.time() - phase_start
    solvable = sum(1 for c in population
                   if c.get('_scores', {}).get('solvable', False))
    avg = sum(c.get('_score', 0) for c in population) / max(1, len(population))
    log(f"  {label}Scored {scored} new ({len(population)} total) in {elapsed:.0f}s "
        f"- {solvable} solvable, avg={avg:.3f}")


# ─── GA operations ───

def select_parents(population, elite_fraction):
    ranked = sorted(population, key=lambda c: c.get('_score', 0), reverse=True)
    count = max(4, int(len(ranked) * elite_fraction))
    return ranked[:count]


def breed_offspring(parents, target_count, mutation_rate, temperature=1.0):
    offspring = []
    while len(offspring) < target_count:
        p1, p2 = random.choices(parents, k=2)
        child = crossover(p1, p2)
        child = mutate(child, mutation_rate, temperature=temperature)
        child['name'] = 'Offspring'
        child.pop('_scores', None)
        child.pop('_score', None)
        child.pop('fitness', None)
        offspring.append(child)
    return offspring


def inject_fresh(count, difficulty_range, tracker=None):
    """Generate fresh courses for diversity injection, biased by tracker."""
    suggestion = tracker.suggest_params() if tracker else {}
    method_weights = suggestion.get('method_weights',
                                     {'aesthetic': 0.5, 'shelf': 0.2,
                                      'component': 0.2, 'diverse': 0.1})
    methods = list(method_weights.keys())
    weights = [method_weights.get(m, 0.25) for m in methods]

    fresh = []
    for _ in range(count):
        seed = random.randint(0, 999999)
        method = random.choices(methods, weights=weights, k=1)[0]
        diff = random.randint(*difficulty_range)
        if method == 'aesthetic':
            template = random.choice(TEMPLATES)
            c = generate_aesthetic_course(seed=seed, template=template,
                                          difficulty=diff)
        elif method == 'component':
            c = generate_component_course(seed=seed, difficulty=diff)
        else:
            c = generate_course(seed=seed, difficulty=diff)
        if validate_course(c):
            c['_gen_params'] = {'method': method, 'difficulty': diff}
            fresh.append(c)
    return fresh


# ─── Mass-generation pipeline (theme-first) ───

def generate_themed_pool(pool_size, difficulty_range, tracker=None):
    """Mass-generate themed courses for filter-first pipeline.

    Generates pool_size courses across all templates with varied seeds.
    Pure geometry — no physics, extremely fast.
    """
    log(f"Mass-generating {pool_size} themed courses...")
    courses = []

    suggestion = tracker.suggest_params() if tracker else {}
    # Distribute across templates, biased by tracker if available
    template_weights = {}
    for t in TEMPLATES:
        rate = tracker.success_rate('template', t) if tracker else 0.5
        template_weights[t] = max(0.05, rate)
    total_w = sum(template_weights.values())

    seed_idx = 0
    for template, weight in template_weights.items():
        count = max(1, int(pool_size * weight / total_w))
        for i in range(count):
            diff = random.randint(*difficulty_range)
            c = generate_aesthetic_course(seed=seed_idx, template=template,
                                          difficulty=diff)
            if validate_course(c):
                c['_gen_params'] = {'method': 'themed', 'difficulty': diff,
                                    'template': template}
                courses.append(c)
            seed_idx += 1
            if len(courses) >= pool_size:
                break
        if len(courses) >= pool_size:
            break

    # Fill remainder if needed
    while len(courses) < pool_size:
        diff = random.randint(*difficulty_range)
        template = random.choice(TEMPLATES)
        c = generate_aesthetic_course(seed=seed_idx, template=template,
                                      difficulty=diff)
        if validate_course(c):
            c['_gen_params'] = {'method': 'themed', 'difficulty': diff,
                                'template': template}
            courses.append(c)
        seed_idx += 1

    # Log template distribution
    by_template = {}
    for c in courses:
        t = c.get('_gen_params', {}).get('template', '?')
        by_template[t] = by_template.get(t, 0) + 1
    dist = ' '.join(f"{t}={n}" for t, n in sorted(by_template.items()))
    log(f"  Generated {len(courses)} courses ({dist})")
    return courses


def _quick_filter_worker(args):
    """Worker for parallel quick filtering."""
    course, max_steps = args
    skip, best_dist = quick_test(course, samples=8, max_steps=max_steps)
    return not skip  # True = passed filter


def quick_filter_pool(pool, max_steps=350, workers=None):
    """Batch quick-filter: keep courses that might be solvable."""
    log(f"Quick-filtering {len(pool)} courses...")
    phase_start = time.time()

    work_items = [(c, max_steps) for c in pool]
    passed = []

    use_parallel = workers != 1 and len(pool) > 10
    if use_parallel:
        try:
            num_workers = workers or os.cpu_count() or 4
            with multiprocessing.Pool(processes=num_workers) as p:
                results = p.map(_quick_filter_worker, work_items)
            passed = [c for c, keep in zip(pool, results) if keep]
        except Exception as e:
            log(f"  Warning: multiprocessing failed ({e}), falling back")
            use_parallel = False

    if not use_parallel:
        for c in pool:
            skip, _ = quick_test(c, samples=8, max_steps=max_steps)
            if not skip:
                passed.append(c)

    elapsed = time.time() - phase_start
    log(f"  Passed: {len(passed)}/{len(pool)} ({100*len(passed)/max(1,len(pool)):.1f}%) in {elapsed:.0f}s")

    # Log per-template pass rates
    template_pass = {}
    template_total = {}
    for c in pool:
        t = c.get('_gen_params', {}).get('template', '?')
        template_total[t] = template_total.get(t, 0) + 1
    for c in passed:
        t = c.get('_gen_params', {}).get('template', '?')
        template_pass[t] = template_pass.get(t, 0) + 1
    parts = []
    for t in sorted(template_total.keys()):
        p_count = template_pass.get(t, 0)
        total = template_total[t]
        parts.append(f"{t}={p_count}/{total}")
    log(f"  By template: {' '.join(parts)}")
    return passed


def run_themed_pipeline(args):
    """Theme-first pipeline: mass generate → filter → score → optional evolve."""
    global _start_time
    _start_time = time.time()

    log("=== K-Maze Themed Pipeline ===")
    log(f"Config: themed_pool={args.themed_pool} evolve={args.evolve} "
        f"evolve_gens={args.evolve_gens}")
    effective_workers = args.workers or os.cpu_count() or 4
    log(f"  angle_steps={args.angle_steps} max_combos={args.max_combos} "
        f"workers={effective_workers}")
    log(f"  target={args.target_count} courses -> {args.output}")

    hall_of_fame = []
    generation_stats = []
    tracker = ParamTracker()

    if args.resume:
        log(f"Resuming from {args.resume}...")
        hall_of_fame, generation_stats = load_progress(args.resume)
        log(f"  Loaded {len(hall_of_fame)} candidates")

    # Phase 1: Mass Generate
    log("")
    log("=== Phase 1: Mass Generate ===")
    pool = generate_themed_pool(args.themed_pool, args.difficulty_range,
                                 tracker=tracker)

    # Phase 2: Quick Filter
    log("")
    log("=== Phase 2: Quick Filter ===")
    survivors = quick_filter_pool(pool, max_steps=args.max_steps,
                                   workers=args.workers)

    if not survivors:
        log("ERROR: No courses passed quick filter! Try increasing --themed-pool")
        return

    # Phase 3: Full Test
    log("")
    log(f"=== Phase 3: Full Test ({len(survivors)} courses) ===")
    score_population(survivors, args.angle_steps, args.max_combos,
                     args.max_steps, label="Test: ", workers=args.workers)

    # Record into tracker
    for c in survivors:
        if '_gen_params' in c and '_score' in c:
            tracker.record(c['_gen_params'], c['_score'])
            # Also record template for per-template tracking
            params = c['_gen_params'].copy()
            tracker.record(params, c['_score'])

    solvable = [c for c in survivors
                if c.get('_scores', {}).get('solvable', False)]
    log(f"  Solvable: {len(solvable)}/{len(survivors)}")
    log(f"  {tracker.summary()}")

    for c in survivors:
        if c.get('_score', 0) > 0.2:
            hall_of_fame.append(copy.deepcopy(c))

    # Phase 4: Optional light evolution of best courses
    if args.evolve and len(solvable) >= 4:
        log("")
        log(f"=== Phase 4: Light Evolution ({args.evolve_gens} gens) ===")

        # Start with top-scored courses
        pop = sorted(survivors, key=lambda c: c.get('_score', 0),
                     reverse=True)[:min(100, len(survivors))]

        for gen in range(args.evolve_gens):
            temperature = max(0.3, 0.6 - 0.3 * (gen / max(1, args.evolve_gens - 1)))

            parents = select_parents(pop, args.elite_fraction)
            offspring = breed_offspring(parents,
                                        len(pop) - len(parents),
                                        args.mutation_rate,
                                        temperature=temperature)
            pop = [copy.deepcopy(p) for p in parents] + offspring

            score_population(pop, args.angle_steps, args.max_combos,
                             args.max_steps,
                             label=f"Evolve G{gen+1}: ",
                             workers=args.workers)

            best_score = max(c.get('_score', 0) for c in pop)
            gen_solvable = sum(1 for c in pop
                               if c.get('_scores', {}).get('solvable'))
            log(f"  Gen {gen+1}: best={best_score:.3f} solvable={gen_solvable}/{len(pop)} "
                f"temp={temperature:.2f}")

            for c in pop:
                if c.get('_score', 0) > 0.3:
                    hall_of_fame.append(copy.deepcopy(c))

    # Phase 5: Final Selection — diversity-aware (spread across templates)
    log("")
    log("=== Phase 5: Final Selection ===")
    log(f"  Total candidates: {len(hall_of_fame)}")

    # Group by template, pick best from each, round-robin
    by_template = {}
    for c in hall_of_fame:
        t = c.get('_aesthetic', {}).get('template', '?')
        by_template.setdefault(t, []).append(c)
    for t in by_template:
        by_template[t] = deduplicate(by_template[t], max_out=50)

    best = []
    seen_fps = set()
    templates_with_courses = [t for t in sorted(by_template.keys())
                               if by_template[t]]
    idx = 0
    while len(best) < args.target_count and templates_with_courses:
        t = templates_with_courses[idx % len(templates_with_courses)]
        if by_template[t]:
            c = by_template[t].pop(0)
            fp = course_fingerprint(c)
            if fp not in seen_fps:
                seen_fps.add(fp)
                best.append(c)
        else:
            templates_with_courses.remove(t)
        idx += 1
        # Safety break
        if idx > args.target_count * 20:
            break

    log(f"  After diverse dedup: {len(best)} unique courses")

    for c in best:
        assign_physics_wobble(c)

    for i, c in enumerate(best):
        score = c.get('_score', 0)
        template = c.get('_aesthetic', {}).get('template', '?')
        c['name'] = f"Themed #{i+1} [{template}] (score={score:.3f})"

    save_final(best, args.output)
    save_progress(hall_of_fame, generation_stats)

    elapsed = time.time() - _start_time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    log("")
    log(f"=== Complete in {hours}h {minutes}m ===")
    if best:
        s = [c.get('_score', 0) for c in best]
        log(f"  Top {len(best)} scores: min={min(s):.3f} avg={sum(s)/len(s):.3f} max={max(s):.3f}")
        solvable_count = sum(1 for c in best
                             if c.get('_scores', {}).get('solvable', False))
        log(f"  Solvable: {solvable_count}/{len(best)}")
        # Template breakdown
        by_t = {}
        for c in best:
            t = c.get('_aesthetic', {}).get('template', '?')
            by_t[t] = by_t.get(t, 0) + 1
        log(f"  Templates: {' '.join(f'{t}={n}' for t, n in sorted(by_t.items()))}")


# ─── Progress ───

def save_progress(hall_of_fame, stats, filename='overnight_progress.json'):
    saveable = []
    for c in hall_of_fame[:200]:
        c2 = {k: v for k, v in c.items() if not k.startswith('_')}
        c2['_cached_score'] = c.get('_score', 0)
        c2['_cached_scores'] = c.get('_scores', {})
        saveable.append(c2)

    with open(filename, 'w') as f:
        json.dump({
            'hall_of_fame': saveable,
            'stats': stats,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, f, indent=2)
    log(f"  Progress saved -> {filename} ({len(saveable)} candidates)")


def load_progress(filename):
    with open(filename) as f:
        data = json.load(f)
    hall = data.get('hall_of_fame', [])
    for c in hall:
        c['_score'] = c.pop('_cached_score', 0)
        c['_scores'] = c.pop('_cached_scores', {})
    return hall, data.get('stats', [])


def save_final(courses, filename):
    output = []
    for c in courses:
        c2 = {k: v for k, v in c.items() if not k.startswith('_')}
        output.append(c2)
    with open(filename, 'w') as f:
        json.dump(output, f, indent=2)
    log(f"Final output: {len(output)} courses -> {filename}")


# ─── Main loop ───

def run_overnight(args):
    global _start_time
    _start_time = time.time()

    log("=== K-Maze Overnight Batch Runner ===")
    log(f"Config: pool={args.pool_size} pop={args.pop_size} "
        f"gens={args.generations} cycles={args.cycles}")
    effective_workers = args.workers or os.cpu_count() or 4
    log(f"  angle_steps={args.angle_steps} max_combos={args.max_combos} "
        f"workers={effective_workers}")
    log(f"  target={args.target_count} courses -> {args.output}")

    hall_of_fame = []
    generation_stats = []
    tracker = ParamTracker()

    if args.resume:
        log(f"Resuming from {args.resume}...")
        hall_of_fame, generation_stats = load_progress(args.resume)
        log(f"  Loaded {len(hall_of_fame)} candidates")

    # Phase 1: Seed pool
    log("")
    log("=== Phase 1: Seed Pool ===")
    pool = generate_seed_pool(args.pool_size, args.difficulty_range,
                               tracker=tracker)

    # Phase 2: Score seed pool
    log("")
    log("=== Phase 2: Score Seed Pool ===")
    score_population(pool, args.angle_steps, args.max_combos,
                     args.max_steps, label="Seed: ", workers=args.workers)

    # Record seed results into tracker
    for c in pool:
        if '_gen_params' in c and '_score' in c:
            tracker.record(c['_gen_params'], c['_score'])
    log(f"  {tracker.summary()}")

    for c in pool:
        if c.get('_score', 0) > 0.2:
            hall_of_fame.append(copy.deepcopy(c))
    log(f"  Hall of fame: {len(hall_of_fame)} candidates after seeding")

    # Phase 3: Evolution
    log("")
    log("=== Phase 3: Evolution ===")

    total_gens = args.cycles * args.generations

    pop_ranked = sorted(pool, key=lambda c: c.get('_score', 0), reverse=True)
    population = [copy.deepcopy(c) for c in pop_ranked[:args.pop_size]]

    while len(population) < args.pop_size:
        fresh = inject_fresh(1, args.difficulty_range, tracker=tracker)
        population.extend(fresh)

    global_gen = 0

    for cycle in range(args.cycles):
        log(f"")
        log(f"--- Cycle {cycle + 1}/{args.cycles} ---")

        for gen in range(args.generations):
            global_gen += 1

            # Temperature: 1.0 -> 0.2 linear decay
            temperature = max(0.2, 1.0 - 0.8 * (global_gen / total_gens))

            score_population(population, args.angle_steps, args.max_combos,
                             args.max_steps, label=f"C{cycle+1}G{gen+1}: ",
                             workers=args.workers)

            # Record into tracker
            for c in population:
                if '_gen_params' in c and '_score' in c:
                    tracker.record(c['_gen_params'], c['_score'])

            scores_list = [c.get('_score', 0) for c in population]
            solvable = sum(1 for c in population
                           if c.get('_scores', {}).get('solvable', False))
            best = max(scores_list) if scores_list else 0
            avg = sum(scores_list) / max(1, len(scores_list))

            generation_stats.append({
                'cycle': cycle + 1, 'gen': gen + 1, 'global_gen': global_gen,
                'solvable': solvable, 'pop': len(population),
                'best': round(best, 4), 'avg': round(avg, 4),
                'hall': len(hall_of_fame),
                'temperature': round(temperature, 2),
                'time': time.strftime('%H:%M:%S'),
            })

            log(f"  Gen {global_gen}: best={best:.3f} avg={avg:.3f} "
                f"solvable={solvable}/{len(population)} hall={len(hall_of_fame)} "
                f"temp={temperature:.2f}")

            # Hall of fame update
            ranked = sorted(population, key=lambda c: c.get('_score', 0),
                            reverse=True)
            for c in ranked[:10]:
                if c.get('_score', 0) > 0.3:
                    hall_of_fame.append(copy.deepcopy(c))

            # Save progress periodically
            if global_gen % args.save_interval == 0:
                hall_of_fame = deduplicate(hall_of_fame, max_out=200)
                save_progress(hall_of_fame, generation_stats)

            # Selection + breeding (with temperature)
            parents = select_parents(population, args.elite_fraction)
            offspring = breed_offspring(parents,
                                        args.pop_size - len(parents),
                                        args.mutation_rate,
                                        temperature=temperature)
            population = [copy.deepcopy(p) for p in parents] + offspring

        # End of cycle: inject fresh diversity (tracker-informed)
        inject_count = max(5, int(args.pop_size * args.injection_rate))
        fresh = inject_fresh(inject_count, args.difficulty_range,
                             tracker=tracker)
        log(f"  Injecting {len(fresh)} fresh courses")
        log(f"  {tracker.summary()}")
        population.sort(key=lambda c: c.get('_score', 0), reverse=True)
        population = population[:args.pop_size - len(fresh)] + fresh

    # Phase 4: Finalize
    log("")
    log("=== Phase 4: Final Selection ===")

    for c in population:
        if c.get('_score', 0) > 0.2:
            hall_of_fame.append(copy.deepcopy(c))

    log(f"  Total candidates: {len(hall_of_fame)}")
    best = deduplicate(hall_of_fame, max_out=args.target_count)
    log(f"  After dedup: {len(best)} unique courses")

    for c in best:
        assign_physics_wobble(c)

    for i, c in enumerate(best):
        score = c.get('_score', 0)
        c['name'] = f"Overnight #{i+1} (score={score:.3f})"

    save_final(best, args.output)
    save_progress(hall_of_fame, generation_stats)

    # Summary
    elapsed = time.time() - _start_time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    log("")
    log(f"=== Complete in {hours}h {minutes}m ===")
    log(f"  Total generations: {global_gen}")
    if best:
        s = [c.get('_score', 0) for c in best]
        log(f"  Top {len(best)} scores: min={min(s):.3f} avg={sum(s)/len(s):.3f} max={max(s):.3f}")
        solvable = sum(1 for c in best if c.get('_scores', {}).get('solvable', False))
        log(f"  Solvable: {solvable}/{len(best)}")


# ─── CLI ───

def parse_args():
    p = argparse.ArgumentParser(
        description='Overnight batch runner: generate, evolve, and rank K-Maze courses.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python3 overnight.py                                    # default ~6 hour run
  python3 overnight.py --pool 200 --gens 10 --cycles 3   # shorter ~2 hour run
  python3 overnight.py --resume overnight_progress.json   # resume from checkpoint
  python3 overnight.py -o my_best.json                    # custom output file""")

    p.add_argument('--pool', type=int, default=DEFAULTS['pool_size'],
                   dest='pool_size', help=f"seed pool size (default: {DEFAULTS['pool_size']})")
    p.add_argument('--pop', type=int, default=DEFAULTS['pop_size'],
                   dest='pop_size', help=f"GA population (default: {DEFAULTS['pop_size']})")
    p.add_argument('--gens', type=int, default=DEFAULTS['generations'],
                   dest='generations', help=f"generations per cycle (default: {DEFAULTS['generations']})")
    p.add_argument('--cycles', type=int, default=DEFAULTS['cycles'],
                   help=f"evolve-inject cycles (default: {DEFAULTS['cycles']})")
    p.add_argument('--elite', type=float, default=DEFAULTS['elite_fraction'],
                   dest='elite_fraction', help=f"elite fraction (default: {DEFAULTS['elite_fraction']})")
    p.add_argument('--mut-rate', type=float, default=DEFAULTS['mutation_rate'],
                   dest='mutation_rate', help=f"mutation rate (default: {DEFAULTS['mutation_rate']})")
    p.add_argument('--injection', type=float, default=DEFAULTS['injection_rate'],
                   dest='injection_rate', help=f"fresh injection rate (default: {DEFAULTS['injection_rate']})")
    p.add_argument('--angle-steps', type=int, default=DEFAULTS['angle_steps'],
                   dest='angle_steps', help=f"tester angle steps (default: {DEFAULTS['angle_steps']})")
    p.add_argument('--max-combos', type=int, default=DEFAULTS['max_combos'],
                   dest='max_combos', help=f"max combos per test (default: {DEFAULTS['max_combos']})")
    p.add_argument('--max-steps', type=int, default=DEFAULTS['max_steps'],
                   dest='max_steps', help=f"max sim steps per trial (default: {DEFAULTS['max_steps']})")
    p.add_argument('--target', type=int, default=DEFAULTS['target_count'],
                   dest='target_count', help=f"output count (default: {DEFAULTS['target_count']})")
    p.add_argument('--save-interval', type=int, default=DEFAULTS['save_interval'],
                   dest='save_interval', help=f"save every N gens (default: {DEFAULTS['save_interval']})")
    p.add_argument('--workers', type=int, default=None,
                   help=f'parallel workers (default: cpu_count={os.cpu_count()}). '
                        'Use --workers 1 for sequential')
    p.add_argument('--difficulty', default='1-3',
                   help='difficulty range min-max (default: 1-3)')
    p.add_argument('--resume', default=None,
                   help='resume from progress file')
    p.add_argument('-o', '--output', default='overnight_best.json',
                   help='output filename (default: overnight_best.json)')

    # Themed pipeline options
    p.add_argument('--themed-pool', type=int, default=None,
                   dest='themed_pool',
                   help='use theme-first pipeline with N courses (e.g. 5000)')
    p.add_argument('--evolve', action='store_true', default=True,
                   help='run light evolution after themed filtering (default)')
    p.add_argument('--no-evolve', action='store_false', dest='evolve',
                   help='skip evolution, pure generate-and-filter')
    p.add_argument('--evolve-gens', type=int, default=8,
                   dest='evolve_gens',
                   help='generations for optional evolution phase (default: 8)')

    args = p.parse_args()

    parts = args.difficulty.split('-')
    if len(parts) == 2:
        args.difficulty_range = (int(parts[0]), int(parts[1]))
    else:
        d = int(parts[0])
        args.difficulty_range = (d, d)

    return args


if __name__ == '__main__':
    args = parse_args()
    if args.themed_pool is not None:
        run_themed_pipeline(args)
    else:
        run_overnight(args)
