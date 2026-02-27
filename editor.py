import pygame
import math
import json
import sys
from stock_shapes import get_shape_by_name

pygame.init()
W, H = 800, 600
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("K-Maze Editor: Drag/Add/Delete K's → Test/Snapshot")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 42)
smallfont = pygame.font.Font(None, 24)

# Level data
start_pos = [90.0, 60.0]
target_pos = [680.0, 530.0]
target_r = 25
walls = [
    [[0, 0], [0, 600]],
    [[800, 0], [800, 600]],
    [[0, 600], [800, 600]],
    [[170, 50], [170, 400]],
    [[420, 150], [420, 550]],
]
ks = []  # list of {"center": [x,y], "angle": float}

# Editor state
selected = None  # {'type': 'start'/'target'/'wall'/'k', 'idx': N, ...}
adding_line = False
add_start = None
test_mode = False
balls = []
balls_used = 0
won = False
launch_cooldown = 0
gravity = [0.0, 400.0]
drag_factor = 0.995
ball_r = 10
dt = 1.0 / 60.0
snap_grid = 10

courses = []
current_course_idx = -1  # -1 = no course loaded
dropdown_open = False
courses_backup = None  # Save current level before load

k_drag_start_angle = 0.0
k_current_angle_at_click = 0.0
test_mode_selected_k = None 

# K shape (relative points - stem vertical, arms right)
k_rel_points = [
    [0, -45], [0, 45],          # stem
    [30, 30], [0, 0], [30, -30], # upper arm + connect
    [0, -45]                     # close
]

def load_course(idx):
    global walls, ks, start_pos, target_pos, target_r, courses_backup, current_course_idx
    if 0 <= idx < len(courses):
        courses_backup = {
            'walls': walls[:],
            'ks': [k.copy() for k in ks],
            'start': start_pos[:],
            'target': {'pos': target_pos[:], 'r': target_r}
        }
        course = courses[idx]
        
        walls[:] = course.get('walls', [])
        ks[:] = [k.copy() for k in course.get('ks', [])]
        start_pos[:] = course.get('start', [90, 60])
        
        # Handle target flexibly (list or dict)
        tgt = course.get('target', [680, 530])
        if isinstance(tgt, list):
            # Plain list: assume [x, y] or [x, y, r]
            target_pos[:] = tgt[:2] if len(tgt) >= 2 else [680, 530]
            target_r = tgt[2] if len(tgt) >= 3 else 25
        elif isinstance(tgt, dict):
            # Dict format
            target_pos[:] = tgt.get('pos', [680, 530])
            target_r = tgt.get('r', 25)
        else:
            # Fallback
            target_pos[:] = [680, 530]
            target_r = 25
        
        current_course_idx = idx
        name = course.get('name', f'Course {idx}')
        print(f"Loaded {name}!")

def snap(val):
    return round(val / snap_grid) * snap_grid

def rotate_points(points, angle, center):
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    rotated = []
    for px, py in points:
        rx = center[0] + px * cos_a - py * sin_a
        ry = center[1] + px * sin_a + py * cos_a
        rotated.append([rx, ry])
    return rotated

def dist_to_line(pos, p1, p2):
    line_vec = [p2[0] - p1[0], p2[1] - p1[1]]
    line_len_sq = line_vec[0]**2 + line_vec[1]**2
    if line_len_sq == 0: return math.hypot(pos[0] - p1[0], pos[1] - p1[1])
    d = ((pos[0] - p1[0]) * line_vec[0] + (pos[1] - p1[1]) * line_vec[1]) / line_len_sq
    t = max(0, min(1, d))
    closest = [p1[0] + t * line_vec[0], p1[1] + t * line_vec[1]]
    return math.hypot(pos[0] - closest[0], pos[1] - closest[1])

def point_in_circle(pos, center, radius):
    return math.hypot(pos[0] - center[0], pos[1] - center[1]) < radius

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

try:
    with open('maze_courses.json', 'r') as f:
        courses = json.load(f)
    print(f"Loaded {len(courses)} courses!")
except FileNotFoundError:
    print("No maze_courses.json — gen some first!")
    courses = []

running = True
while running:
    current_time = pygame.time.get_ticks()
    keys = pygame.key.get_pressed()
    mx, my = pygame.mouse.get_pos()
    mpos = [mx, my]

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
                balls = []
                balls_used = 0
                won = False
            if event.key == pygame.K_a and not test_mode:
                adding_line = True
            if event.key == pygame.K_k and not test_mode:  # ← Add K!
                ks.append({"center": [snap(mx), snap(my)], "angle": 0.0})
                print("K added!")
            if event.key == pygame.K_s and not test_mode:
                level_data = {
                    "start": start_pos,
                    "target": {"pos": target_pos, "r": target_r},
                    "walls": walls,
                    "ks": [{"center": k["center"], "angle": k["angle"]} for k in ks]
                }
                with open("level.json", "w") as f:
                    json.dump(level_data, f, indent=2)
                pygame.image.save(screen, "level.png")
                print("Saved level.json + level.png")
            if event.key == pygame.K_1 and not test_mode:  # Drop corridor_h
                shape = get_shape_by_name('corridor_h')
                if shape:
                    offset_walls = [[[x + snap(mx), y + snap(my)] for x,y in wall] for wall in shape['walls']]
                    walls.extend(offset_walls)
                    print(f"Dropped {shape['name']}")
            if event.key == pygame.K_2 and not test_mode:  # Drop corridor_v
                shape = get_shape_by_name('corridor_v')
                if shape:
                    offset_walls = [[[x + snap(mx), y + snap(my)] for x,y in wall] for wall in shape['walls']]
                    walls.extend(offset_walls)
                    print(f"Dropped {shape['name']}")
            if event.key == pygame.K_3 and not test_mode:  # Drop pipe
                shape = get_shape_by_name('pipe')
                if shape:
                    offset_walls = [[[x + snap(mx), y + snap(my)] for x,y in wall] for wall in shape['walls']]
                    walls.extend(offset_walls)
                    print(f"Dropped {shape['name']}")
            if event.key == pygame.K_4 and not test_mode:  # Drop funnel
                shape = get_shape_by_name('funnel')
                if shape:
                    offset_walls = [[[x + snap(mx), y + snap(my)] for x,y in wall] for wall in shape['walls']]
                    walls.extend(offset_walls)
                    print(f"Dropped {shape['name']}")
            if event.key == pygame.K_5 and not test_mode:  # Drop room
                shape = get_shape_by_name('room')
                if shape:
                    offset_walls = [[[x + snap(mx), y + snap(my)] for x,y in wall] for wall in shape['walls']]
                    walls.extend(offset_walls)
                    print(f"Dropped {shape['name']}")
            if event.key == pygame.K_t:
                test_mode = not test_mode
                if not test_mode:
                    balls = []
                    balls_used = 0
                    won = False
            if event.key == pygame.K_l and not test_mode:  # Toggle dropdown
                dropdown_open = not dropdown_open
            if event.key == pygame.K_UP and dropdown_open and not test_mode:
                current_course_idx = (current_course_idx - 1) % max(1, len(courses))
            if event.key == pygame.K_DOWN and dropdown_open and not test_mode:
                current_course_idx = (current_course_idx + 1) % max(1, len(courses))
            if event.key == pygame.K_RETURN and dropdown_open and not test_mode:  # Load selected
                load_course(current_course_idx)
            
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                if dropdown_open:
                    for i in range(len(courses)):
                        rect = pygame.Rect(10, 80 + i * 25, 300, 22)
                        if rect.collidepoint(mx, my):
                            load_course(i)
                            dropdown_open = False  # Auto-close
                            break
                if adding_line and not test_mode:
                    if add_start is None:
                        add_start = [snap(mx), snap(my)]
                    else:
                        walls.append([add_start, [snap(mx), snap(my)]])
                        adding_line = False
                        add_start = None
                else:
                    # In test mode: only allow selecting K for rotation
                    if test_mode:
                        test_mode_selected_k = None
                        for i, k in enumerate(ks):
                            if point_in_circle(mpos, k["center"], 60):  # generous hit anywhere on K
                                test_mode_selected_k = i
                                dx = mx - k["center"][0]
                                dy = my - k["center"][1]
                                k_drag_start_angle = math.atan2(dy, dx)
                                k_current_angle_at_click = k["angle"]
                                break
                    else:
                        # Editor mode (normal selection logic)
                        selected = None
                        for i, k in enumerate(ks):
                            if point_in_circle(mpos, k["center"], 20):
                                selected = {'type': 'k', 'idx': i, 'mode': 'move'}
                                dx = mx - k["center"][0]
                                dy = my - k["center"][1]
                                k_drag_start_angle = math.atan2(dy, dx)
                                k_current_angle_at_click = k["angle"]
                                break
                            elif point_in_circle(mpos, k["center"], 60):
                                selected = {'type': 'k', 'idx': i, 'mode': 'rotate'}
                                dx = mx - k["center"][0]
                                dy = my - k["center"][1]
                                k_drag_start_angle = math.atan2(dy, dx)
                                k_current_angle_at_click = k["angle"]
                                break
                        if selected is None:
                            # start / target / walls selection (unchanged)
                            if point_in_circle(mpos, start_pos, 20):
                                selected = {'type': 'start'}
                            elif point_in_circle(mpos, target_pos, target_r + 10):
                                selected = {'type': 'target'}
                            else:
                                min_dist = 12
                                closest_wall = -1
                                closest_end = -1
                                for i, wall in enumerate(walls):
                                    d1 = math.hypot(mx - wall[0][0], my - wall[0][1])
                                    d2 = math.hypot(mx - wall[1][0], my - wall[1][1])
                                    d_line = dist_to_line(mpos, wall[0], wall[1])
                                    if d1 < min_dist:
                                        min_dist, closest_wall, closest_end = d1, i, 0
                                    if d2 < min_dist:
                                        min_dist, closest_wall, closest_end = d2, i, 1
                                    if d_line < min_dist and d_line < 8:
                                        min_dist, closest_wall, closest_end = d_line, i, -1
                                if closest_wall != -1:
                                    selected = {'type': 'wall', 'idx': closest_wall, 'end': closest_end}
        if event.type == pygame.MOUSEBUTTONUP:
            selected = None
            test_mode_selected_k = None  
        if event.type == pygame.MOUSEMOTION and selected and not test_mode:
            if selected['type'] == 'start':
                start_pos[:] = [snap(mx), snap(my)]
            elif selected['type'] == 'target':
                target_pos[:] = [snap(mx), snap(my)]
            elif selected['type'] == 'wall':
                wall = walls[selected['idx']]
                if selected['end'] == -1:
                    dx = mx - (wall[0][0] + wall[1][0]) / 2
                    dy = my - (wall[0][1] + wall[1][1]) / 2
                    wall[0][0] += dx; wall[0][1] += dy
                    wall[1][0] += dx; wall[1][1] += dy
                else:
                    wall[selected['end']] = [snap(mx), snap(my)]
            elif selected['type'] == 'k':
                k = ks[selected['idx']]
                
                if selected.get('mode') == 'move':
                    k["center"] = [snap(mx), snap(my)]
                
                elif selected.get('mode') == 'rotate':
                    dx = mx - k["center"][0]
                    dy = my - k["center"][1]
                    current_mouse_angle = math.atan2(dy, dx)
                    delta = current_mouse_angle - k_drag_start_angle
                    k["angle"] = k_current_angle_at_click + delta
                    # Optional: snap to nicer angles
                    # step = math.radians(15)
                    # k["angle"] = round(k["angle"] / step) * step
        if event.type == pygame.MOUSEMOTION and not test_mode and selected:
            # Existing editor motion logic (start, target, wall, k move/rotate) — unchanged
            if selected['type'] == 'start':
                start_pos[:] = [snap(mx), snap(my)]
            # ... rest of your existing editor motion code ...
            elif selected['type'] == 'k':
                k = ks[selected['idx']]
                if selected.get('mode') == 'move':
                    k["center"] = [snap(mx), snap(my)]
                elif selected.get('mode') == 'rotate':
                    dx = mx - k["center"][0]
                    dy = my - k["center"][1]
                    current_mouse_angle = math.atan2(dy, dx)
                    delta = current_mouse_angle - k_drag_start_angle
                    k["angle"] = k_current_angle_at_click + delta

        # NEW: Allow rotation in test mode (independent of 'selected')
        if event.type == pygame.MOUSEMOTION and test_mode and test_mode_selected_k is not None:
            k = ks[test_mode_selected_k]
            dx = mx - k["center"][0]
            dy = my - k["center"][1]
            current_mouse_angle = math.atan2(dy, dx)
            delta = current_mouse_angle - k_drag_start_angle
            k["angle"] = k_current_angle_at_click + delta
            # Optional snap:
            # step = math.radians(15)
            # k["angle"] = round(k["angle"] / step) * step

    if test_mode:
        if keys[pygame.K_SPACE] and current_time - launch_cooldown > 300:
            balls.append({'pos': start_pos[:], 'vel': [0.0, 0.0]})
            balls_used += 1
            launch_cooldown = current_time

        new_balls = []
        for ball in balls:
            ball['vel'][0] += gravity[0] * dt
            ball['vel'][1] += gravity[1] * dt
            ball['pos'][0] += ball['vel'][0] * dt
            ball['pos'][1] += ball['vel'][1] * dt
            ball['vel'][0] *= drag_factor
            ball['vel'][1] *= drag_factor

            # Wall collisions
            for wall in walls:
                reflect_ball_over_line(ball['pos'], ball['vel'], wall[0], wall[1], ball_r)

            # K collisions (each edge)
            for k in ks:
                rot_points = rotate_points(k_rel_points, k["angle"], k["center"])
                for i in range(len(rot_points) - 1):
                    reflect_ball_over_line(ball['pos'], ball['vel'], rot_points[i], rot_points[i+1], ball_r)

            if ball['pos'][0] < -50 or ball['pos'][0] > W + 50 or ball['pos'][1] > H + 50 or ball['pos'][1] < -50:
                continue

            dx = ball['pos'][0] - target_pos[0]
            dy = ball['pos'][1] - target_pos[1]
            if math.hypot(dx, dy) < target_r + ball_r:
                won = True
                print(f"WIN with {balls_used} balls!")
                continue

            new_balls.append(ball)
        balls = new_balls

    # Draw everything
    screen.fill((15, 15, 30))
    # Grid
    for x in range(0, W, snap_grid): pygame.draw.line(screen, (25,25,50), (x,0), (x,H))
    for y in range(0, H, snap_grid): pygame.draw.line(screen, (25,25,50), (0,y), (W,y))

    # Walls
    for wall in walls:
        pygame.draw.line(screen, (220,220,220), wall[0], wall[1], 8)
        pygame.draw.circle(screen, (255,200,200), wall[0], 5)
        pygame.draw.circle(screen, (255,200,200), wall[1], 5)

    # K's
    for k in ks:
        rot = rotate_points(k_rel_points, k["angle"], k["center"])
        pygame.draw.lines(screen, (0, 220, 220), True, rot, 10)   # thick cyan
        pygame.draw.lines(screen, (0, 255, 255), True, rot, 5)
        pygame.draw.circle(screen, (255,255,100), k["center"], 8)  # yellow grip

    # Start & Target
    pygame.draw.circle(screen, (120,120,255), start_pos, 12)
    pygame.draw.circle(screen, (80,255,120), target_pos, target_r)
    pygame.draw.circle(screen, (150,255,180), target_pos, target_r // 2)

    # Adding line preview
    if adding_line and add_start:
        pygame.draw.line(screen, (255,255,0), add_start, mpos, 2)

    # Balls in test
    if test_mode:
        for b in balls:
            pygame.draw.circle(screen, (255,120,120), (int(b['pos'][0]), int(b['pos'][1])), ball_r)
            
    # Course loader dropdown
    if dropdown_open:
        pygame.draw.rect(screen, (40,40,60), (5, 75, 310, min(250, len(courses)*25 + 10)))  # Backdrop
        for i, course in enumerate(courses):
            y = 80 + i * 25
            name = course.get('name', f'Course {i}')
            color = (255,255,200) if i == current_course_idx else (200,200,200)
            text = smallfont.render(name[:25] + '...' if len(name)>25 else name, True, color)
            screen.blit(text, (15, y))
        pygame.draw.rect(screen, (100,200,255), (10, 80 + current_course_idx*25, 300, 22), 2)  # Highlight

    # Current course info
    if current_course_idx >= 0:
        course_name = courses[current_course_idx].get('name', f'Course {current_course_idx}')
        ctext = smallfont.render(f"Loaded: {course_name[:20]}", True, (150,255,150))
        screen.blit(ctext, (10, H-30))

    # UI
    mode = "EDIT" if not test_mode else "TEST"
    text = font.render(f"{mode} | Balls: {balls_used}", True, (255,255,255))
    screen.blit(text, (10,10))
    inst = smallfont.render("K: Add K | A: Add line | Drag center: move K / near edge: rotate | Right-click: delete | T: Test | S: Save", True, (180,220,255))
    screen.blit(inst, (10,40))
    if won:
        wintext = font.render(f"WIN! {balls_used} balls", True, (255,255,120))
        screen.blit(wintext, (150,250))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()