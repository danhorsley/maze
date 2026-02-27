"""Automated course quality scorer for K-Maze.

Tests courses by searching over K angle configurations using the canonical
physics engine. Scores each course on solvability, difficulty, and quality.

Usage:
    python3 level_tester.py                              # test maze_courses.json
    python3 level_tester.py -i custom.json               # test custom file
    python3 level_tester.py -o scored.json               # output scored JSON
    python3 level_tester.py --angles 24                  # finer search (15-degree steps)
    python3 level_tester.py --filter-solvable            # only output solvable courses
"""
import argparse
import json
import math
import random
import itertools

from physics import (
    BALL_R, PLAYFIELD_W, PLAYFIELD_H,
    simulate_ball,
)

MAX_COMBOS = 1000  # cap to keep runtime sane in pure Python


def test_course(course, angle_steps=12, max_combos=MAX_COMBOS, max_steps=600):
    """Test a single course by grid-searching K angle combinations.

    Args:
        course: Course dict with walls, ks, start, target.
        angle_steps: Number of angle steps per K (12 = 30-degree increments).
        max_combos: Maximum angle combos to test (random sample if exceeded).
        max_steps: Max simulation steps per trial (default: 600).

    Returns:
        Dict of scores for this course.
    """
    walls = course['walls']
    ks = course['ks']
    start = course['start']
    tgt = course['target']
    target_pos = tgt['pos'] if isinstance(tgt, dict) else tgt[:2]
    target_r = tgt.get('r', 25) if isinstance(tgt, dict) else 25

    angles = [i * 2 * math.pi / angle_steps for i in range(angle_steps)]

    num_ks = len(ks)
    if num_ks == 0:
        angle_combos = [()]
    else:
        full_count = angle_steps ** num_ks
        if full_count <= max_combos:
            angle_combos = list(itertools.product(angles, repeat=num_ks))
        else:
            # Random sampling when full grid is too large
            angle_combos = [
                tuple(random.choice(angles) for _ in range(num_ks))
                for _ in range(max_combos)
            ]

    total_combos = len(angle_combos)
    wins = 0
    best_min_dist = float('inf')
    best_win = None       # best winning config stats
    best_any_steps = 0    # longest survival across all configs
    best_any_wall = 0
    best_any_k = 0

    for combo in angle_combos:
        # Build K configs with these angles
        ks_test = []
        for i, k in enumerate(ks):
            ks_test.append({
                'center': k['center'][:],
                'angle': combo[i] if i < len(combo) else 0.0,
            })

        pos = start[:]
        vel = [0.0, 0.0]
        final_pos, final_vel, steps, wall_hits, k_hits, trajectory = \
            simulate_ball(pos, vel, walls, ks_test, max_steps=max_steps,
                          target=tgt, record_trajectory=False)

        # Track best stats across all configs
        if steps > best_any_steps:
            best_any_steps = steps
            best_any_wall = wall_hits
            best_any_k = k_hits

        # Get target proximity from inline tracking
        tgt_info = trajectory[-1] if trajectory else {'min_dist': float('inf'), 'hit': False}
        hit_target = tgt_info['hit']
        trial_min_dist = tgt_info['min_dist']

        best_min_dist = min(best_min_dist, trial_min_dist)

        if hit_target:
            wins += 1
            total_k_segs = max(1, num_ks * 5)  # 5 segments per K shape
            k_dep = min(1.0, k_hits / total_k_segs)

            if best_win is None or k_dep > best_win[3] or \
               (k_dep == best_win[3] and steps < best_win[2]):
                best_win = (wall_hits, k_hits, steps, k_dep)

    scores = {
        'solvable': wins > 0,
        'solve_rate': round(wins / total_combos, 4) if total_combos > 0 else 0,
        'best_min_dist': round(best_min_dist, 1),
    }

    if best_win:
        scores['k_dependency'] = round(best_win[3], 2)
        scores['path_length'] = best_win[2]
        scores['wall_bounces'] = best_win[0]
        scores['k_bounces'] = best_win[1]
    else:
        # Use best stats from any config even if none won
        total_k_segs = max(1, num_ks * 5)
        scores['k_dependency'] = round(min(1.0, best_any_k / total_k_segs), 2)
        scores['path_length'] = best_any_steps
        scores['wall_bounces'] = best_any_wall
        scores['k_bounces'] = best_any_k

    return scores


def main():
    p = argparse.ArgumentParser(
        description='Test K-Maze courses for solvability and quality.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python3 level_tester.py                              # test maze_courses.json
  python3 level_tester.py -i custom.json               # test custom file
  python3 level_tester.py -o scored.json               # output scored JSON
  python3 level_tester.py --angles 24                  # finer 15-degree search
  python3 level_tester.py --filter-solvable -o good.json""")

    p.add_argument('-i', '--input', default='maze_courses.json',
                   help='input courses JSON (default: maze_courses.json)')
    p.add_argument('-o', '--output', default=None,
                   help='output scored courses JSON (optional)')
    p.add_argument('--angles', type=int, default=12,
                   help='angle steps per K shape (default: 12 = 30-degree)')
    p.add_argument('--max-combos', type=int, default=MAX_COMBOS,
                   help=f'max angle combos per course (default: {MAX_COMBOS})')
    p.add_argument('--filter-solvable', action='store_true',
                   help='only output solvable courses')

    args = p.parse_args()

    with open(args.input) as f:
        courses = json.load(f)

    print(f"Testing {len(courses)} courses from {args.input}")
    print(f"  angle steps: {args.angles} ({360 // args.angles}-degree increments)")
    num_ks_range = (
        min(len(c['ks']) for c in courses) if courses else 0,
        max(len(c['ks']) for c in courses) if courses else 0,
    )
    print(f"  K shapes per course: {num_ks_range[0]}-{num_ks_range[1]}")

    # Estimate combos for largest case
    max_combos = args.angles ** num_ks_range[1] if num_ks_range[1] > 0 else 1
    print(f"  max combos per course: {max_combos}")
    print()

    solved_count = 0
    total_solve_rate = 0
    total_k_dep = 0
    results = []

    for i, course in enumerate(courses):
        num_ks = len(course['ks'])
        combos = min(args.angles ** num_ks if num_ks > 0 else 1, args.max_combos)
        print(f"[{i+1}/{len(courses)}] Testing ({num_ks} Ks, {combos} combos)... ", end='', flush=True)
        scores = test_course(course, angle_steps=args.angles, max_combos=args.max_combos)
        course['scores'] = scores
        results.append(course)

        if scores['solvable']:
            solved_count += 1
            total_solve_rate += scores['solve_rate']
            total_k_dep += scores['k_dependency']

        # Print result on same line as progress
        if scores['solvable']:
            print(f"SOLVABLE  solve_rate={scores['solve_rate']:.4f}  "
                  f"k_dep={scores['k_dependency']:.2f}  "
                  f"path={scores['path_length']}  "
                  f"bounces={scores['wall_bounces']}w/{scores['k_bounces']}k")
        else:
            print(f"FAIL      best_dist={scores['best_min_dist']:.1f}  "
                  f"k_dep={scores['k_dependency']:.2f}  "
                  f"path={scores['path_length']}  "
                  f"bounces={scores['wall_bounces']}w/{scores['k_bounces']}k")

    # Summary
    print()
    print(f"Summary: {solved_count}/{len(courses)} solvable")
    if solved_count > 0:
        print(f"  avg solve_rate (solvable only): {total_solve_rate / solved_count:.4f}")
        print(f"  avg k_dependency (solvable only): {total_k_dep / solved_count:.2f}")

    # Output
    if args.output:
        output = results
        if args.filter_solvable:
            output = [c for c in results if c['scores']['solvable']]
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\nSaved {len(output)} courses -> {args.output}")


if __name__ == '__main__':
    main()
