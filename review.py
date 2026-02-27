"""Course reviewer for K-Maze.

Browse overnight/batch results, play-test courses, and tag them as
keep / skip / favourite. Saves verdicts to a review JSON so you can
filter the best courses later.

Usage:
    python3 review.py                          # auto-detect overnight_best.json
    python3 review.py batch1.json batch2.json  # merge multiple batches
    python3 review.py --resume review.json     # continue a previous session

Keys:
    LEFT/RIGHT  - prev/next course
    SPACE       - launch ball (play-test)
    Drag K      - rotate K shape
    R           - reset balls
    Y           - tag KEEP
    N           - tag SKIP
    F           - tag FAVOURITE
    U           - clear tag (untag)
    S           - save review progress
    Q / ESC     - save and quit
"""
import pygame
import math
import json
import sys
import os
import time
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


def load_batches(paths):
    """Load and merge courses from multiple files. Tags each with source."""
    all_courses = []
    for path in paths:
        try:
            courses = load_courses_from_file(path)
            for c in courses:
                c['_source'] = os.path.basename(path)
            all_courses.extend(courses)
            print(f"Loaded {len(courses)} courses from {path}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load {path}: {e}")
    return all_courses


def load_review(path):
    """Load a previous review session. Returns (courses, verdicts)."""
    with open(path) as f:
        data = json.load(f)
    courses = data.get('courses', [])
    verdicts = data.get('verdicts', {})
    print(f"Resumed review: {len(courses)} courses, "
          f"{sum(1 for v in verdicts.values() if v)} tagged")
    return courses, verdicts


def save_review(path, courses, verdicts):
    """Save review state: courses + verdict tags."""
    # Strip internal fields from courses before saving
    clean = []
    for c in courses:
        c2 = {k: v for k, v in c.items() if not k.startswith('_')}
        c2['_source'] = c.get('_source', '')
        clean.append(c2)
    with open(path, 'w') as f:
        json.dump({'courses': clean, 'verdicts': verdicts,
                   'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')}, f, indent=2)
    print(f"Saved review -> {path} ({len(verdicts)} verdicts)")


def export_kept(review_path, output_path=None):
    """Export kept/favourite courses from a review file."""
    with open(review_path) as f:
        data = json.load(f)
    courses = data['courses']
    verdicts = data.get('verdicts', {})
    kept = []
    for i, c in enumerate(courses):
        v = verdicts.get(str(i), '')
        if v in ('keep', 'favourite'):
            c2 = {k: v for k, v in c.items() if not k.startswith('_')}
            kept.append(c2)
    if output_path is None:
        output_path = review_path.replace('.json', '_kept.json')
    with open(output_path, 'w') as f:
        json.dump(kept, f, indent=2)
    print(f"Exported {len(kept)} courses -> {output_path}")
    return kept


# ─── Resolve input files ───

review_file = 'review.json'
courses = []
verdicts = {}  # str(index) -> 'keep'|'skip'|'favourite'|''

# Parse args
resume_path = None
input_files = []
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == '--resume' and i + 1 < len(args):
        resume_path = args[i + 1]
        i += 2
    elif args[i] == '--export' and i + 1 < len(args):
        # Export mode: just export and exit
        export_kept(args[i + 1], args[i + 2] if i + 2 < len(args) else None)
        sys.exit(0)
    elif args[i] == '-o' and i + 1 < len(args):
        review_file = args[i + 1]
        i += 2
    else:
        input_files.append(args[i])
        i += 1

if resume_path:
    courses, verdicts = load_review(resume_path)
    review_file = resume_path
elif input_files:
    courses = load_batches(input_files)
else:
    # Auto-detect
    for candidate in ['overnight_best.json', 'maze_courses.json']:
        if os.path.exists(candidate):
            courses = load_batches([candidate])
            break

if not courses:
    print("No courses found. Usage: python3 review.py [file1.json file2.json ...]")
    sys.exit(1)

print(f"Reviewing {len(courses)} courses -> {review_file}")

# ─── Pygame init ───

pygame.init()
W, H = PLAYFIELD_W, PLAYFIELD_H
screen = pygame.display.set_mode((W, H + 80))  # extra space for review UI
clock = pygame.time.Clock()
font = pygame.font.Font(None, 42)
smallfont = pygame.font.Font(None, 24)
tinyfont = pygame.font.Font(None, 20)

# ─── Game state ───

walls = []
ks = []
start_pos = [90.0, 60.0]
target_pos = [680, 530]
target_r = 25
k_centers = []   # per-K centers
k_angles = []    # per-K angles (all interactive)
active_k = -1    # which K is being dragged (-1 = none)
balls = []
balls_used = 0
won = False
launch_cooldown = 0
rotating = False
prev_mouse_angle = 0.0
current_idx = 0

gravity = list(GRAVITY)
drag_factor = DRAG
wall_restitution = RESTITUTION
k_restitution_val = K_RESTITUTION

VERDICT_COLORS = {
    'keep': (100, 255, 100),
    'skip': (255, 100, 100),
    'favourite': (255, 255, 50),
    '': (120, 120, 120),
}


def load_course(idx):
    global walls, ks, start_pos, target_pos, target_r, current_idx
    global gravity, drag_factor, wall_restitution, k_restitution_val
    global k_centers, k_angles, active_k, balls, balls_used, won

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

    phys = course.get('physics', {})
    gravity[:] = [0.0, phys.get('gravity', GRAVITY[1])]
    drag_factor = phys.get('drag', DRAG)
    wall_restitution = phys.get('restitution', RESTITUTION)
    k_restitution_val = phys.get('k_restitution', K_RESTITUTION)

    k_centers = [list(k['center']) for k in ks]
    k_angles = [k.get('angle', 0.0) for k in ks]
    active_k = -1

    balls = []
    balls_used = 0
    won = False
    current_idx = idx

    name = course.get('name', f'Course {idx + 1}')
    v = verdicts.get(str(idx), '')
    tag = f" [{v.upper()}]" if v else ""
    pygame.display.set_caption(f"K-Maze Review: {name}{tag}")


def set_verdict(tag):
    """Tag current course. Empty string clears."""
    verdicts[str(current_idx)] = tag
    name = courses[current_idx].get('name', f'Course {current_idx + 1}')
    label = f" [{tag.upper()}]" if tag else ""
    pygame.display.set_caption(f"K-Maze Review: {name}{label}")


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
            if event.key == pygame.K_ESCAPE or event.key == pygame.K_q:
                running = False
            elif event.key == pygame.K_r:
                balls = []
                balls_used = 0
                won = False
                k_angles = [k.get('angle', 0.0) for k in ks]
            elif event.key == pygame.K_LEFT:
                load_course(current_idx - 1)
            elif event.key == pygame.K_RIGHT:
                load_course(current_idx + 1)
            elif event.key == pygame.K_y:
                set_verdict('keep')
            elif event.key == pygame.K_n:
                set_verdict('skip')
            elif event.key == pygame.K_f:
                set_verdict('favourite')
            elif event.key == pygame.K_u:
                set_verdict('')
            elif event.key == pygame.K_s:
                save_review(review_file, courses, verdicts)
        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = pygame.mouse.get_pos()
            if my < H:  # only interact in playfield area
                # Find closest K-gate center
                for ki, kc in enumerate(k_centers):
                    dist = math.hypot(mx - kc[0], my - kc[1])
                    if dist < 60:
                        active_k = ki
                        rotating = True
                        prev_mouse_angle = math.atan2(my - kc[1],
                                                       mx - kc[0])
                        break
        if event.type == pygame.MOUSEMOTION and rotating and active_k >= 0:
            mx, my = event.pos
            kc = k_centers[active_k]
            curr_angle = math.atan2(my - kc[1], mx - kc[0])
            delta = curr_angle - prev_mouse_angle
            k_angles[active_k] += delta
            prev_mouse_angle = curr_angle
        if event.type == pygame.MOUSEBUTTONUP:
            rotating = False
            active_k = -1

    # Launch
    if keys_pressed[pygame.K_SPACE] and current_time - launch_cooldown > 300:
        balls.append({'pos': start_pos[:], 'vel': [0.0, 0.0]})
        balls_used += 1
        launch_cooldown = current_time

    # Build K segments (all Ks use live angles)
    all_k_segs = []
    for ki in range(len(k_centers)):
        rot = rotate_points(K_REL_POINTS, k_angles[ki], k_centers[ki])
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

        for seg_start, seg_end in walls:
            reflect_ball_over_line(ball['pos'], ball['vel'], seg_start, seg_end,
                                   BALL_R, wall_restitution)
        for seg_start, seg_end in all_k_segs:
            reflect_ball_over_line(ball['pos'], ball['vel'], seg_start, seg_end,
                                   BALL_R, k_restitution_val)

        if (ball['pos'][0] < 0 or ball['pos'][0] > W or
                ball['pos'][1] > H or ball['pos'][1] < -50):
            continue
        dx = ball['pos'][0] - target_pos[0]
        dy = ball['pos'][1] - target_pos[1]
        if math.hypot(dx, dy) < target_r + BALL_R:
            won = True
            continue
        new_balls.append(ball)
    balls = new_balls

    # ─── Draw playfield ───
    screen.fill((15, 15, 30))

    for s1, s2 in walls:
        pygame.draw.line(screen, (220, 220, 220),
                         (int(s1[0]), int(s1[1])), (int(s2[0]), int(s2[1])), 8)

    for ki in range(len(k_centers)):
        rot = rotate_points(K_REL_POINTS, k_angles[ki], k_centers[ki])
        pygame.draw.lines(screen, (100, 255, 150), True, rot, 10)
        pygame.draw.lines(screen, (0, 255, 255), True, rot, 6)
        pygame.draw.circle(screen, (255, 255, 0),
                           (int(k_centers[ki][0]), int(k_centers[ki][1])), 6)

    for b in balls:
        pygame.draw.circle(screen, (255, 120, 120),
                           (int(b['pos'][0]), int(b['pos'][1])), BALL_R)

    pygame.draw.circle(screen, (80, 255, 120),
                       (int(target_pos[0]), int(target_pos[1])), target_r)
    pygame.draw.circle(screen, (150, 255, 180),
                       (int(target_pos[0]), int(target_pos[1])), target_r // 2)
    pygame.draw.circle(screen, (120, 120, 120),
                       (int(start_pos[0]), int(start_pos[1])), 7)

    if won:
        wintext = font.render(f"WIN! {balls_used} balls", True, (255, 255, 120))
        screen.blit(wintext, (150, 250))

    # ─── Draw review panel (below playfield) ───
    panel_y = H + 2
    pygame.draw.rect(screen, (30, 30, 50), (0, H, W, 80))
    pygame.draw.line(screen, (80, 80, 100), (0, H), (W, H), 2)

    # Course info
    course = courses[current_idx]
    name = course.get('name', f'Course {current_idx + 1}')
    source = course.get('_source', '')
    phys = course.get('physics', {})

    info = f"{current_idx + 1}/{len(courses)}  {name}"
    if source:
        info += f"  [{source}]"
    screen.blit(smallfont.render(info, True, (200, 220, 255)), (10, panel_y + 4))

    # Physics summary
    g_val = phys.get('gravity', 400.0)
    d_val = phys.get('drag', 0.995)
    r_val = phys.get('restitution', 0.85)
    kr_val = phys.get('k_restitution', 1.05)
    phys_text = (f"g={g_val:.0f}  drag={d_val:.4f}  rest={r_val:.3f}  "
                 f"k_rest={kr_val:.3f}  walls={len(course.get('walls', []))}  "
                 f"ks={len(course.get('ks', []))}  balls={balls_used}")
    screen.blit(tinyfont.render(phys_text, True, (150, 150, 180)), (10, panel_y + 26))

    # Verdict + controls
    v = verdicts.get(str(current_idx), '')
    v_label = v.upper() if v else "UNTAGGED"
    v_color = VERDICT_COLORS.get(v, (120, 120, 120))
    screen.blit(font.render(v_label, True, v_color), (10, panel_y + 44))

    controls = "Y:Keep  N:Skip  F:Fav  U:Untag  S:Save  Q:Quit"
    screen.blit(tinyfont.render(controls, True, (140, 140, 160)),
                (W - 340, panel_y + 55))

    # Progress bar: how many tagged vs total
    tagged = sum(1 for v in verdicts.values() if v)
    bar_w = 200
    bar_x = W - bar_w - 10
    bar_y = panel_y + 8
    pygame.draw.rect(screen, (50, 50, 70), (bar_x, bar_y, bar_w, 14))
    if len(courses) > 0:
        fill_w = int(bar_w * tagged / len(courses))
        pygame.draw.rect(screen, (80, 200, 120), (bar_x, bar_y, fill_w, 14))
    prog_text = tinyfont.render(f"{tagged}/{len(courses)} tagged", True,
                                (180, 220, 180))
    screen.blit(prog_text, (bar_x, bar_y + 16))

    # Mini verdict strip: show all courses as colored dots
    strip_y = panel_y + 44
    strip_x = 200
    dot_w = max(2, min(6, (W - strip_x - 20) // max(1, len(courses))))
    for ci in range(len(courses)):
        cv = verdicts.get(str(ci), '')
        color = VERDICT_COLORS.get(cv, (60, 60, 60))
        if ci == current_idx:
            color = (255, 255, 255)
        x = strip_x + ci * dot_w
        if x + dot_w < W - 10:
            pygame.draw.rect(screen, color, (x, strip_y, dot_w - 1, 10))

    pygame.display.flip()
    clock.tick(60)

# Auto-save on exit
save_review(review_file, courses, verdicts)
pygame.quit()
