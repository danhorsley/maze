"""Component tester for K-Maze.

Tests individual components in isolation by wrapping them in minimal
test courses and simulating balls through entry -> exit.

Usage:
    python3 component_tester.py                    # test all components
    python3 component_tester.py -c funnel          # test specific component
    python3 component_tester.py --sweep funnel     # parameter sweep
    python3 component_tester.py --verbose          # show per-trial details
    python3 component_tester.py -o results.json    # save JSON
"""
import argparse
import math
import json

from physics import (
    GRAVITY, BALL_R, PLAYFIELD_W, PLAYFIELD_H,
    simulate_ball, dist_to_line,
)
from stock_shapes import (
    get_component, list_components, translate_component,
    COMPONENT_REGISTRY,
)


def ball_crossed_line(trajectory, line_a, line_b):
    """Check if any trajectory point is within BALL_R+2 of the exit line."""
    threshold = BALL_R + 2
    for pt in trajectory:
        if dist_to_line(pt, line_a, line_b) < threshold:
            return True
    return False


def generate_entry_velocities(component, num_angles=8, num_speeds=3):
    """Generate test velocities aimed from entry toward exit."""
    entry = component["entry"]
    exit_ = component["exit"]

    entry_cx = (entry["a"][0] + entry["b"][0]) / 2
    entry_cy = (entry["a"][1] + entry["b"][1]) / 2
    exit_cx = (exit_["a"][0] + exit_["b"][0]) / 2
    exit_cy = (exit_["a"][1] + exit_["b"][1]) / 2

    dx = exit_cx - entry_cx
    dy = exit_cy - entry_cy
    base_angle = math.atan2(dy, dx)

    bbox = component["bbox"]
    comp_height = max(bbox[3] - bbox[1], 50)
    freefall_speed = math.sqrt(2 * abs(GRAVITY[1]) * comp_height)

    velocities = []
    spread = math.pi / 4  # +/- 45 degrees
    for ai in range(num_angles):
        angle = base_angle - spread + (2 * spread * ai / max(1, num_angles - 1))
        for si in range(num_speeds):
            speed = freefall_speed * (0.5 + si * 0.5)
            velocities.append([speed * math.cos(angle), speed * math.sin(angle)])

    velocities.append([0.0, 0.0])  # zero-velocity drop
    return velocities


def wrap_component_as_course(component):
    """Place a component in a minimal test course with boundary walls."""
    bbox = component["bbox"]
    comp_w = bbox[2] - bbox[0]
    comp_h = bbox[3] - bbox[1]

    place_x = (PLAYFIELD_W - comp_w) / 2 - bbox[0]
    place_y = max(80, (PLAYFIELD_H - comp_h) / 2 - bbox[1])

    placed = translate_component(component, place_x, place_y)

    boundary = [
        [[0, 0], [0, PLAYFIELD_H]],
        [[PLAYFIELD_W, 0], [PLAYFIELD_W, PLAYFIELD_H]],
        [[0, PLAYFIELD_H], [PLAYFIELD_W, PLAYFIELD_H]],
    ]

    course = {
        "walls": boundary + placed["walls"],
        "ks": placed["ks"],
        "start": [
            (placed["entry"]["a"][0] + placed["entry"]["b"][0]) / 2,
            (placed["entry"]["a"][1] + placed["entry"]["b"][1]) / 2,
        ],
        "target": {
            "pos": [
                (placed["exit"]["a"][0] + placed["exit"]["b"][0]) / 2,
                (placed["exit"]["a"][1] + placed["exit"]["b"][1]) / 2,
            ],
            "r": 25,
        },
    }
    return course, placed


def test_component(component, num_angles=8, num_speeds=3,
                   max_steps=300, verbose=False):
    """Test a single component in isolation.

    Returns dict with pass_rate, avg_steps, avg_bounces, k_interaction.
    """
    course, placed = wrap_component_as_course(component)
    velocities = generate_entry_velocities(placed, num_angles, num_speeds)

    exit_a = placed["exit"]["a"]
    exit_b = placed["exit"]["b"]

    passes = 0
    total_steps = 0
    total_bounces = 0
    k_interaction_count = 0

    for vel in velocities:
        pos = course["start"][:]
        _, _, steps, wall_hits, k_hits, trajectory = \
            simulate_ball(pos, vel[:], course["walls"], course["ks"], max_steps)

        crossed = ball_crossed_line(trajectory, exit_a, exit_b)

        if crossed:
            passes += 1
            total_steps += steps
            total_bounces += wall_hits + k_hits
            if k_hits > 0:
                k_interaction_count += 1

        if verbose:
            status = "PASS" if crossed else "FAIL"
            print(f"    vel=({vel[0]:>6.0f},{vel[1]:>6.0f}) {status}  "
                  f"steps={steps}  bounces={wall_hits}w/{k_hits}k")

    total = len(velocities)
    return {
        "name": component["name"],
        "trials": total,
        "passes": passes,
        "pass_rate": round(passes / total, 4) if total > 0 else 0,
        "avg_steps": round(total_steps / passes, 1) if passes > 0 else 0,
        "avg_bounces": round(total_bounces / passes, 1) if passes > 0 else 0,
        "k_interaction": round(k_interaction_count / passes, 2) if passes > 0 else 0,
    }


def parameter_sweep(base_name, param_name, values):
    """Sweep one parameter, test each value. Returns list of results."""
    results = []
    for val in values:
        comp = get_component(base_name, **{param_name: val})
        if comp is None:
            continue
        result = test_component(comp)
        result["param_value"] = val
        results.append(result)
    return results


SWEEP_CONFIGS = {
    "funnel": [
        ("width", [60, 80, 100, 120, 150, 180, 220]),
        ("neck_width", [20, 25, 30, 40, 50]),
    ],
    "trampoline": [
        ("wall_angle", [5, 10, 15, 20, 25, 30, 40]),
        ("width", [80, 120, 150, 200]),
    ],
    "cannon_up": [
        ("angle_deg", [-80, -70, -60, -50, -40, -30]),
        ("length", [80, 100, 120, 150, 180]),
    ],
    "bouncy_room": [
        ("width", [100, 130, 150, 180, 200]),
        ("opening_width", [25, 30, 40, 50, 60]),
    ],
    "gate": [
        ("gap", [20, 22, 25, 30, 35, 40, 50]),
        ("height", [40, 60, 80, 100, 120]),
    ],
    "ramp_lr": [
        ("width", [100, 150, 200, 250, 300]),
        ("height", [40, 60, 80, 100, 120]),
    ],
}


def main():
    p = argparse.ArgumentParser(
        description="Test K-Maze components in isolation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python3 component_tester.py                    # test all components
  python3 component_tester.py -c funnel          # test one component
  python3 component_tester.py --sweep funnel     # parameter sweep
  python3 component_tester.py --verbose          # per-trial details""")

    p.add_argument("-c", "--component", default=None,
                   help="test a specific component (default: all)")
    p.add_argument("--sweep", default=None,
                   help="run parameter sweep for a component")
    p.add_argument("--verbose", action="store_true",
                   help="show per-trial details")
    p.add_argument("--angles", type=int, default=8,
                   help="number of entry angle variations (default: 8)")
    p.add_argument("--speeds", type=int, default=3,
                   help="number of speed variations (default: 3)")
    p.add_argument("-o", "--output", default=None,
                   help="save results to JSON file")
    args = p.parse_args()

    if args.sweep:
        name = args.sweep
        if name not in SWEEP_CONFIGS:
            print(f"No sweep config for '{name}'. Available: {list(SWEEP_CONFIGS.keys())}")
            return

        print(f"Parameter sweep: {name}")
        all_results = {}
        for param_name, values in SWEEP_CONFIGS[name]:
            print(f"\n  Sweeping {param_name}: {values}")
            sweep_results = parameter_sweep(name, param_name, values)
            for r in sweep_results:
                status = "OK" if r["pass_rate"] > 0.3 else "WEAK" if r["pass_rate"] > 0 else "FAIL"
                print(f"    {param_name}={r['param_value']:>6}  "
                      f"pass={r['pass_rate']:.2f}  "
                      f"bounces={r['avg_bounces']:.1f}  "
                      f"steps={r['avg_steps']:.0f}  [{status}]")
            all_results[param_name] = sweep_results

        if args.output:
            with open(args.output, "w") as f:
                json.dump(all_results, f, indent=2)
            print(f"\nSaved -> {args.output}")
        return

    if args.component:
        names = [args.component]
    else:
        names = list_components()

    print(f"Testing {len(names)} components "
          f"({args.angles} angles x {args.speeds} speeds + 1 drop)")
    print()

    results = []
    for name in names:
        comp = get_component(name)
        if comp is None:
            print(f"  {name}: NOT FOUND")
            continue

        if args.verbose:
            print(f"  {name}:")
        else:
            print(f"  {name:<20}", end="", flush=True)

        result = test_component(comp, args.angles, args.speeds,
                                verbose=args.verbose)
        results.append(result)

        status = "OK" if result["pass_rate"] > 0.3 else \
                 "WEAK" if result["pass_rate"] > 0 else "FAIL"
        line = (f"pass={result['pass_rate']:.2f}  "
                f"bounces={result['avg_bounces']:.1f}  "
                f"steps={result['avg_steps']:.0f}  "
                f"k_int={result['k_interaction']:.2f}  [{status}]")
        if args.verbose:
            print(f"  -> {line}")
        else:
            print(line)

    print()
    ok = sum(1 for r in results if r["pass_rate"] > 0.3)
    weak = sum(1 for r in results if 0 < r["pass_rate"] <= 0.3)
    fail = sum(1 for r in results if r["pass_rate"] == 0)
    print(f"Summary: {ok} OK / {weak} WEAK / {fail} FAIL  (total: {len(results)})")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Saved results -> {args.output}")


if __name__ == "__main__":
    main()
