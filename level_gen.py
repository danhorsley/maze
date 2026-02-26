import random
import math
import json
import copy  # for deep copies

k_rel_points = [
    [0, -45], [0, 45],          # stem
    [30, 30], [0, 0], [30, -30], # upper arm + connect
    [0, -45]                     # close
]

def rotate_points(points, angle, center):
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    rotated = []
    for px, py in points:
        rx = center[0] + px * cos_a - py * sin_a
        ry = center[1] + px * sin_a + py * cos_a
        rotated.append([rx, ry])
    return rotated

def reflect_ball_over_line(pos, vel, p1, p2, r):
    line_vec = [p2[0] - p1[0], p2[1] - p1[1]]
    line_len_sq = line_vec[0]**2 + line_vec[1]**2
    if line_len_sq == 0: return False
    d = ((pos[0] - p1[0]) * line_vec[0] + (pos[1] - p1[1]) * line_vec[1]) / line_len_sq
    t = max(0, min(1, d))
    closest = [p1[0] + t * line_vec[0], p1[1] + t * line_vec[1]]
    dx = pos[0] - closest[0]
    dy = pos[1] - closest[1]
    dist = math.sqrt(dx**2 + dy**2)
    if dist > r or dist == 0: return False
    nx = dx / dist
    ny = dy / dist
    penetration = r - dist
    pos[0] += nx * penetration * 1.001
    pos[1] += ny * penetration * 1.001
    dot = vel[0] * nx + vel[1] * ny
    vel[0] -= 2 * dot * nx
    vel[1] -= 2 * dot * ny
    vel[0] *= 0.85
    vel[1] *= 0.85
    return True

def detect_collision(pos, p1, p2, r):
    """Detect hit without modifying pos/vel."""
    line_vec = [p2[0] - p1[0], p2[1] - p1[1]]
    line_len_sq = line_vec[0]**2 + line_vec[1]**2
    if line_len_sq == 0: return False
    d = ((pos[0] - p1[0]) * line_vec[0] + (pos[1] - p1[1]) * line_vec[1]) / line_len_sq
    t = max(0, min(1, d))
    closest = [p1[0] + t * line_vec[0], p1[1] + t * line_vec[1]]
    dx = pos[0] - closest[0]
    dy = pos[1] - closest[1]
    dist = math.sqrt(dx**2 + dy**2)
    return dist < r

def simulate_level(walls, ks, max_balls=3, trials=5) -> float:
    """Avg fitness over trials; partial credit."""
    best_fitness = 0
    for _ in range(trials):  # Multi-trial for better eval
        ks_angles = [random.uniform(0, math.pi*2) for _ in ks]  # Random per trial
        min_dist = float('inf')
        k_hits = 0
        for balls_used in range(1, max_balls + 1):
            pos = [90.0, 60.0]
            vel = [0.0, 0.0]
            steps = 0
            alive = True
            while alive and steps < 600:  # Shorter cap
                vel[1] += 400.0 / 60
                pos[0] += vel[0] / 60
                pos[1] += vel[1] / 60
                vel[0] *= 0.98  # Livelier air drag
                vel[1] *= 0.98

                # Off-screen fail
                if not (0 < pos[0] < 800 and 0 < pos[1] < 600):
                    alive = False
                    break

                # Walls: detect only, instant lose
                hit_wall = False
                for wall in walls:
                    if detect_collision(pos, wall[0], wall[1], 10):
                        hit_wall = True
                        alive = False
                        break
                if hit_wall: break

                # Ks: reflect, count hits
                for idx, k in enumerate(ks):
                    k['angle'] = ks_angles[idx]  # Fixed per trial
                    rot_pts = rotate_points(k_rel_points, k['angle'], k['center'])
                    for i in range(len(rot_pts)-1):
                        if reflect_ball_over_line(pos, vel, rot_pts[i], rot_pts[i+1], 10):
                            k_hits += 1

                # Target check
                cur_dist = math.hypot(pos[0]-680, pos[1]-530)
                min_dist = min(min_dist, cur_dist)
                if cur_dist < 35:
                    fitness = 1.0 / balls_used + 0.3 * (k_hits / max(1, len(ks)))  # Bonus for Ks used
                    best_fitness = max(best_fitness, fitness)
                    alive = False

                steps += 1
        # Partial if no win: inverse min_dist + survival
        if best_fitness == 0:
            partial = (600 - min_dist) / 600 * 0.2 + steps / 600 * 0.1
            best_fitness = max(best_fitness, partial)
    return best_fitness / trials  # Avg

# GA params
POP, GENS, MUT_RATE = 100, 500, 0.3

def rand_level():
    # Constrained: outer bounds + random corridors-like
    base_walls = [[[0,0],[0,600]], [[800,0],[800,600]], [[0,600],[800,600]]]  # Bounds
    extra_walls = []
    for _ in range(random.randint(3,5)):  # 3-5 segments
        x1, y1 = random.uniform(50,750), random.uniform(50,550)
        x2 = x1 + random.uniform(-150,150)
        y2 = y1 + random.uniform(-150,150)
        extra_walls.append([[x1,y1],[x2,y2]])
    walls = base_walls + extra_walls

    ks = []
    for _ in range(random.randint(2,4)):
        # Place in open-ish space (away from start/target)
        cx = random.uniform(150,650)
        cy = random.uniform(100,500)
        while math.hypot(cx-90, cy-60) < 100 or math.hypot(cx-680, cy-530) < 100:
            cx, cy = random.uniform(150,650), random.uniform(100,500)
        ks.append({'center': [cx, cy], 'angle': random.uniform(0, math.pi*2)})
    return {'walls': walls, 'ks': ks, 'start': [90,60], 'target': {'pos': [680,530], 'r':25}}

pop = [rand_level() for _ in range(POP)]
for g in range(GENS):
    # Compute fitness once per level and attach it
    for level in pop:
        level['fitness'] = simulate_level(level['walls'], level['ks'])

    scored = sorted(pop, key=lambda l: l['fitness'], reverse=True)
    print(f"Gen {g}: Best {scored[0]['fitness']:.3f}")
    elites = scored[:POP//4]  # More elites
    offspring = []
    while len(offspring) < POP:
        p1, p2 = random.choices(elites, k=2)
        child = copy.deepcopy(p1)
        # Crossover walls + ks
        mid_w = len(child['walls']) // 2
        child['walls'][mid_w:] = copy.deepcopy(p2['walls'][mid_w:])
        mid_k = len(child['ks']) // 2
        child['ks'][mid_k:] = copy.deepcopy(p2['ks'][mid_k:])
        # Mutate stronger
        for wall in child['walls']:
            if random.random() < MUT_RATE:
                wall[0][0] += random.gauss(0, 50)
                wall[0][1] += random.gauss(0, 50)
                wall[1][0] += random.gauss(0, 50)
                wall[1][1] += random.gauss(0, 50)
        for k in child['ks']:
            if random.random() < MUT_RATE:
                k['center'][0] += random.gauss(0, 40)
                k['center'][1] += random.gauss(0, 40)
                k['angle'] += random.gauss(0, 0.5)
        offspring.append(child)
    pop = elites + offspring[:POP - len(elites)]  # Keep elites

# Save top (fitness >0.3)
goods = [l for l in scored if simulate_level(l['walls'], l['ks']) > 0.3][:50]
with open('auto_levels.json', 'w') as f:
    json.dump(goods, f, indent=2)
print(f"Saved {len(goods)} auto-levels!")