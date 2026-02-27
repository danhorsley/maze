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
from maze_gen import generate_course, generate_component_course, validate_course
from level_tester import test_course
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
    'max_steps': 400,
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


# ─── Scoring ───

def composite_score(scores):
    """Score a tested course 0.0-1.0 for gameplay quality."""
    if not scores['solvable']:
        return 0.05 * max(0, 1.0 - scores['best_min_dist'] / 600)

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

    # Path length (15%): 100-400 steps is interesting
    pl = scores['path_length']
    if pl < 50:
        s += 0.05
    elif pl <= 400:
        s += 0.05 + 0.10 * min(1.0, (pl - 50) / 200)
    else:
        s += 0.15 * max(0.3, 1.0 - (pl - 400) / 200)

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


def generate_seed_pool(pool_size, difficulty_range):
    """Generate initial diverse pool from three sources."""
    log(f"Generating seed pool of {pool_size} courses...")
    courses = []

    # 40% shelf-based with varied parameters
    shelf_count = int(pool_size * 0.4)
    for i in range(shelf_count):
        diff = random.randint(*difficulty_range)
        slope = random.choice([None, 0.04, 0.06, 0.08, 0.10, 0.12])
        gap_range = random.choice([(40, 60), (50, 80), (60, 100), (70, 90)])
        c = generate_course(seed=i, difficulty=diff, slope=slope,
                            gap_width_range=gap_range)
        if validate_course(c):
            courses.append(c)

    # 35% component-based
    comp_count = int(pool_size * 0.35)
    for i in range(comp_count):
        diff = random.randint(*difficulty_range)
        c = generate_component_course(seed=shelf_count + i, difficulty=diff)
        if validate_course(c):
            courses.append(c)

    # 25% diverse random
    random_target = pool_size - len(courses)
    for i in range(random_target):
        c = rand_level_diverse(seed=shelf_count + comp_count + i)
        if validate_course(c):
            courses.append(c)

    log(f"  Generated {len(courses)} valid courses")
    return courses


# ─── Testing ───

def _score_worker(args):
    """Worker function for multiprocessing. Scores a single course."""
    course, angle_steps, max_combos, max_steps = args
    scores = test_course(course, angle_steps=angle_steps,
                         max_combos=max_combos, max_steps=max_steps)
    score = composite_score(scores)
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
                scores = test_course(course, angle_steps=angle_steps,
                                     max_combos=max_combos, max_steps=max_steps)
                course['_scores'] = scores
                course['_score'] = composite_score(scores)
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


def breed_offspring(parents, target_count, mutation_rate):
    offspring = []
    while len(offspring) < target_count:
        p1, p2 = random.choices(parents, k=2)
        child = crossover(p1, p2)
        child = mutate(child, mutation_rate)
        child['name'] = 'Offspring'
        child.pop('_scores', None)
        child.pop('_score', None)
        child.pop('fitness', None)
        offspring.append(child)
    return offspring


def inject_fresh(count, difficulty_range):
    fresh = []
    for _ in range(count):
        seed = random.randint(0, 999999)
        if random.random() < 0.5:
            c = generate_component_course(seed=seed,
                                          difficulty=random.randint(*difficulty_range))
        else:
            c = generate_course(seed=seed,
                                difficulty=random.randint(*difficulty_range))
        if validate_course(c):
            fresh.append(c)
    return fresh


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

    if args.resume:
        log(f"Resuming from {args.resume}...")
        hall_of_fame, generation_stats = load_progress(args.resume)
        log(f"  Loaded {len(hall_of_fame)} candidates")

    # Phase 1: Seed pool
    log("")
    log("=== Phase 1: Seed Pool ===")
    pool = generate_seed_pool(args.pool_size, args.difficulty_range)

    # Phase 2: Score seed pool
    log("")
    log("=== Phase 2: Score Seed Pool ===")
    score_population(pool, args.angle_steps, args.max_combos,
                     args.max_steps, label="Seed: ", workers=args.workers)

    for c in pool:
        if c.get('_score', 0) > 0.2:
            hall_of_fame.append(copy.deepcopy(c))
    log(f"  Hall of fame: {len(hall_of_fame)} candidates after seeding")

    # Phase 3: Evolution
    log("")
    log("=== Phase 3: Evolution ===")

    pop_ranked = sorted(pool, key=lambda c: c.get('_score', 0), reverse=True)
    population = [copy.deepcopy(c) for c in pop_ranked[:args.pop_size]]

    while len(population) < args.pop_size:
        fresh = inject_fresh(1, args.difficulty_range)
        population.extend(fresh)

    global_gen = 0

    for cycle in range(args.cycles):
        log(f"")
        log(f"--- Cycle {cycle + 1}/{args.cycles} ---")

        for gen in range(args.generations):
            global_gen += 1

            score_population(population, args.angle_steps, args.max_combos,
                             args.max_steps, label=f"C{cycle+1}G{gen+1}: ",
                             workers=args.workers)

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
                'time': time.strftime('%H:%M:%S'),
            })

            log(f"  Gen {global_gen}: best={best:.3f} avg={avg:.3f} "
                f"solvable={solvable}/{len(population)} hall={len(hall_of_fame)}")

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

            # Selection + breeding
            parents = select_parents(population, args.elite_fraction)
            offspring = breed_offspring(parents,
                                        args.pop_size - len(parents),
                                        args.mutation_rate)
            population = [copy.deepcopy(p) for p in parents] + offspring

        # End of cycle: inject fresh diversity
        inject_count = max(5, int(args.pop_size * args.injection_rate))
        fresh = inject_fresh(inject_count, args.difficulty_range)
        log(f"  Injecting {len(fresh)} fresh courses")
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
    run_overnight(args)
