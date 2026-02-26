import random
import math
import json

# PASTE YOUR FUNCS HERE (from editor.py)
k_rel_points = [[0, -45], [0, 45], [30, 30], [0, 0], [30, -30], [0, -45]]  # example
def rotate_points(points, angle, center): ...  # full
def reflect_ball_over_line(pos, vel, p1, p2, r): ...  # full

def simulate_level(walls, ks, max_balls=3) -> float:
    """0-1 fitness: high if 1-ball win, low if fails."""
    for balls_used in range(1, max_balls + 1):
        pos = [90.0, 60.0]
        vel = [0.0, 0.0]
        steps = 0
        while steps < 1200:  # ~20s sim
            vel[1] += 400 / 60
            pos[0] += vel[0] / 60
            pos[1] += vel[1] / 60
            vel[0] *= 0.94  # bouncy
            vel[1] *= 0.94

            # AI rotates nearest K toward target
            tgt_dir = math.atan2(530 - pos[1], 680 - pos[0])
            for k in ks:
                k['angle'] = tgt_dir  # greedy

            # Walls = instant lose
            for wall in walls:
                if reflect_ball_over_line(pos, vel, *wall, 10):
                    break  # lose
            else:  # no wall hit: K reflects
                for k in ks:
                    rot_pts = rotate_points(k_rel_points, k['angle'], k['center'])
                    for i in range(len(rot_pts)-1):
                        reflect_ball_over_line(pos, vel, rot_pts[i], rot_pts[i+1], 10)

            if math.hypot(pos[0]-680, pos[1]-530) < 35:
                return 1.0 / balls_used  # perfect!

            steps += 1
    return 0.0

# GA
POP, GENS, MUT = 50, 150, 0.15
def rand_level():
    walls = [[[random.uniform(0,800), random.uniform(0,600)] for _ in range(2)] for _ in range(6)]
    ks = [{'center': [random.uniform(100,700), random.uniform(100,500)], 'angle': 0} for _ in range(3)]
    return {'walls': walls, 'ks': ks, 'start': [90,60], 'target': {'pos': [680,530], 'r':25}}

pop = [rand_level() for _ in range(POP)]
for g in range(GENS):
    scored = sorted(pop, key=lambda l: simulate_level(l['walls'], l['ks']), reverse=True)
    print(f"Gen {g}: Best {simulate_level(scored[0]['walls'], scored[0]['ks']):.3f}")
    elites = scored[:POP//3]
    offspring = []
    while len(offspring) < POP:
        p1, p2 = random.choices(elites, k=2)
        child = p1.copy()
        # Xover: swap half walls
        mid = len(child['walls']) // 2
        child['walls'][mid:] = p2['walls'][mid:].copy()
        # Mutate
        for wall in child['walls']:
            for pt in wall:
                pt[0] += random.gauss(0, 25)
                pt[1] += random.gauss(0, 25)
        for k in child['ks']:
            k['center'][0] += random.gauss(0, 20) if random.random() < MUT else 0
            k['center'][1] += random.gauss(0, 20) if random.random() < MUT else 0
            k['angle'] += random.gauss(0, 0.3) if random.random() < MUT else 0
        offspring.append(child)
    pop = offspring[:POP]

# Save top 50 (filter >0.2 fitness)
goods = [l for l in scored if simulate_level(l['walls'], l['ks']) > 0.2][:50]
with open('auto_levels.json', 'w') as f:
    json.dump(goods, f, indent=2)
print(f"Saved {len(goods)} auto-levels! Load in editor.")