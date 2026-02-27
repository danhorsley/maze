import pygame
import math
import json
import sys
import os
from physics import (
    K_REL_POINTS, GRAVITY, DRAG, BALL_R, DT, RESTITUTION, K_RESTITUTION,
    PLAYFIELD_W, PLAYFIELD_H,
    rotate_points, reflect_ball_over_line,
)

# ─── Course loading ───

def load_courses_from_file(path):
    """Load courses from a JSON file. Returns list of course dicts."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return [data]


# Resolution chain: CLI arg > overnight_best.json > maze_courses.json > level.json
courses = []
course_file = None

if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    course_file = sys.argv[1]
else:
    for candidate in ['overnight_best.json', 'maze_courses.json', 'level.json']:
        if os.path.exists(candidate):
            course_file = candidate
            break

if course_file:
    try:
        courses = load_courses_from_file(course_file)
        print(f"Loaded {len(courses)} courses from {course_file}")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Could not load {course_file}: {e}")

if not courses:
    courses = [{
        'walls': [
            [[0, 0], [0, 600]], [[800, 0], [800, 600]], [[0, 600], [800, 600]],
            [[170, 50], [170, 400]], [[420, 150], [420, 550]],
        ],
        'start': [90.0, 60.0],
        'target': {'pos': [680, 530], 'r': 25},
        'ks': [{'center': [140.0, 250.0], 'angle': 0.0}],
        'name': 'Default',
    }]

# ─── Pygame init ───

pygame.init()
W, H = PLAYFIELD_W, PLAYFIELD_H
screen = pygame.display.set_mode((W, H))
clock = pygame.time.Clock()
font = pygame.font.Font(None, 42)
smallfont = pygame.font.Font(None, 24)

# ─── Game state ───

walls = []
ks = []
start_pos = [90.0, 60.0]
target_pos = [680, 530]
target_r = 25
k_center = [W / 2, H / 2]
k_angle = 0.0
balls = []
balls_used = 0
won = False
launch_cooldown = 0
rotating = False
prev_mouse_angle = 0.0
current_course_idx = 0

# Per-course physics (overridable via course["physics"])
gravity = list(GRAVITY)
drag_factor = DRAG
wall_restitution = RESTITUTION
k_restitution_val = K_RESTITUTION


def load_course(idx):
    global walls, ks, start_pos, target_pos, target_r, current_course_idx
    global gravity, drag_factor, wall_restitution, k_restitution_val
    global k_center, k_angle, balls, balls_used, won

    idx = idx % len(courses)
    course = courses[idx]

    walls = course.get('walls', [])
    ks = course.get('ks', [])
    start_pos = list(course.get('start', [90, 60]))

    tgt = course.get('target', {'pos': [680, 530], 'r': 25})
    if isinstance(tgt, dict):
        target_pos = list(tgt.get('pos', [680, 530]))
        target_r = tgt.get('r', 25)
    elif isinstance(tgt, list):
        target_pos = list(tgt[:2])
        target_r = tgt[2] if len(tgt) >= 3 else 25
    else:
        target_pos = [680, 530]
        target_r = 25

    # Physics overrides
    phys = course.get('physics', {})
    gravity[:] = [0.0, phys.get('gravity', GRAVITY[1])]
    drag_factor = phys.get('drag', DRAG)
    wall_restitution = phys.get('restitution', RESTITUTION)
    k_restitution_val = phys.get('k_restitution', K_RESTITUTION)

    # Interactive K = first K shape; rest are static
    if ks:
        k_center = list(ks[0]['center'])
        k_angle = ks[0].get('angle', 0.0)
    else:
        k_center = [W / 2, H / 2]
        k_angle = 0.0

    balls = []
    balls_used = 0
    won = False
    current_course_idx = idx

    name = course.get('name', f'Course {idx + 1}')
    pygame.display.set_caption(f"K-Maze: {name}")


load_course(0)

# ─── Main loop ───

running = True
while running:
    current_time = pygame.time.get_ticks()
    keys_pressed = pygame.key.get_pressed()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
                balls = []
                balls_used = 0
                won = False
                if ks:
                    k_angle = ks[0].get('angle', 0.0)
                else:
                    k_angle = 0.0
            if event.key == pygame.K_LEFT:
                load_course(current_course_idx - 1)
            if event.key == pygame.K_RIGHT:
                load_course(current_course_idx + 1)
        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = pygame.mouse.get_pos()
            dist = math.hypot(mx - k_center[0], my - k_center[1])
            if dist < 60:
                rotating = True
                prev_mouse_angle = math.atan2(my - k_center[1], mx - k_center[0])
        if event.type == pygame.MOUSEMOTION and rotating:
            mx, my = event.pos
            curr_angle = math.atan2(my - k_center[1], mx - k_center[0])
            delta = curr_angle - prev_mouse_angle
            k_angle += delta
            prev_mouse_angle = curr_angle
        if event.type == pygame.MOUSEBUTTONUP:
            rotating = False

    # Launch (SPACE, throttled)
    if keys_pressed[pygame.K_SPACE] and current_time - launch_cooldown > 300:
        balls.append({'pos': start_pos[:], 'vel': [0.0, 0.0]})
        balls_used += 1
        launch_cooldown = current_time

    # Build K segments: interactive K + static Ks
    all_k_segs = []
    if ks:
        rot_k = rotate_points(K_REL_POINTS, k_angle, k_center)
        all_k_segs.extend((rot_k[i], rot_k[i + 1]) for i in range(len(rot_k) - 1))
    for k in ks[1:]:
        rot = rotate_points(K_REL_POINTS, k.get('angle', 0.0), k['center'])
        all_k_segs.extend((rot[i], rot[i + 1]) for i in range(len(rot) - 1))

    # Update balls
    new_balls = []
    for ball in balls:
        ball['vel'][0] += gravity[0] * DT
        ball['vel'][1] += gravity[1] * DT
        ball['pos'][0] += ball['vel'][0] * DT
        ball['pos'][1] += ball['vel'][1] * DT
        ball['vel'][0] *= drag_factor
        ball['vel'][1] *= drag_factor

        # Wall collisions
        for seg_start, seg_end in walls:
            reflect_ball_over_line(ball['pos'], ball['vel'], seg_start, seg_end,
                                   BALL_R, wall_restitution)

        # K collisions (all K shapes)
        for seg_start, seg_end in all_k_segs:
            reflect_ball_over_line(ball['pos'], ball['vel'], seg_start, seg_end,
                                   BALL_R, k_restitution_val)

        # Out of bounds = dead
        if (ball['pos'][0] < 0 or ball['pos'][0] > W or
                ball['pos'][1] > H or ball['pos'][1] < -50):
            continue

        # Target hit?
        dx = ball['pos'][0] - target_pos[0]
        dy = ball['pos'][1] - target_pos[1]
        if math.hypot(dx, dy) < target_r + BALL_R:
            won = True
            print(f"WIN with {balls_used} balls!")
            continue

        new_balls.append(ball)
    balls = new_balls

    # ─── Draw ───
    screen.fill((15, 15, 30))

    # Walls
    for s1, s2 in walls:
        pygame.draw.line(screen, (220, 220, 220),
                         (int(s1[0]), int(s1[1])), (int(s2[0]), int(s2[1])), 8)

    # Interactive K (first K, bright)
    if ks:
        rot_k = rotate_points(K_REL_POINTS, k_angle, k_center)
        pygame.draw.lines(screen, (100, 255, 150), True, rot_k, 10)
        pygame.draw.lines(screen, (0, 255, 255), True, rot_k, 6)
        pygame.draw.circle(screen, (255, 255, 0),
                           (int(k_center[0]), int(k_center[1])), 6)

    # Static Ks (dimmer)
    for k in ks[1:]:
        rot = rotate_points(K_REL_POINTS, k.get('angle', 0.0), k['center'])
        pygame.draw.lines(screen, (60, 150, 90), True, rot, 10)
        pygame.draw.lines(screen, (0, 180, 180), True, rot, 5)

    # Balls
    for b in balls:
        pygame.draw.circle(screen, (255, 120, 120),
                           (int(b['pos'][0]), int(b['pos'][1])), BALL_R)

    # Target
    pygame.draw.circle(screen, (80, 255, 120),
                       (int(target_pos[0]), int(target_pos[1])), target_r)
    pygame.draw.circle(screen, (150, 255, 180),
                       (int(target_pos[0]), int(target_pos[1])), target_r // 2)

    # Start pos
    pygame.draw.circle(screen, (120, 120, 120),
                       (int(start_pos[0]), int(start_pos[1])), 7)

    # UI
    text = font.render(f"Balls: {balls_used}", True, (255, 255, 255))
    screen.blit(text, (10, 10))
    course_text = smallfont.render(
        f"Course {current_course_idx + 1}/{len(courses)}", True, (150, 255, 150))
    screen.blit(course_text, (10, 40))
    inst = smallfont.render(
        "SPACE:Launch | Drag K | R:Reset | LEFT/RIGHT:Course", True, (180, 220, 255))
    screen.blit(inst, (10, 58))
    if won:
        wintext = font.render(f"WIN! {balls_used} balls", True, (255, 255, 120))
        screen.blit(wintext, (150, 250))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
