import pygame
import math
import json
import sys

pygame.init()
W, H = 800, 600
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("K-Maze Editor: Drag/Add/Delete → Test/Snapshot")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 42)
smallfont = pygame.font.Font(None, 24)

# Level data (editable)
start_pos = [90.0, 60.0]
target_pos = [680.0, 530.0]
target_r = 25
walls = [  # Default maze
    [[0, 0], [0, 600]],
    [[800, 0], [800, 600]],
    [[0, 600], [800, 600]],
    [[170, 50], [170, 400]],
    [[420, 150], [420, 550]],
]

# Editor state
selected = None  # {'type': 'start'/'target'/'wall', 'idx': N, 'end': 0/1 for line ends}
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
snap_grid = 10  # px

def snap(val):
    return round(val / snap_grid) * snap_grid

def dist_to_line(pos, p1, p2):
    line_vec = [p2[0] - p1[0], p2[1] - p1[1]]
    line_len_sq = line_vec[0]**2 + line_vec[1]**2
    if line_len_sq == 0: return math.hypot(pos[0] - p1[0], pos[1] - p1[1])
    d = ((pos[0] - p1[0]) * line_vec[0] + (pos[1] - p1[1]) * line_vec[1]) / line_len_sq
    t = max(0, min(1, d))
    closest = [p1[0] + t * line_vec[0], p1[1] + t * line_vec[1]]
    return math.hypot(pos[0] - closest[0], pos[1] - closest[1])

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
            if event.key == pygame.K_r:  # Reset level/balls
                balls = []
                balls_used = 0
                won = False
            if event.key == pygame.K_a and not test_mode:  # Add line
                adding_line = True
            if event.key == pygame.K_s and not test_mode:  # Snapshot
                level_data = {
                    "start": start_pos,
                    "target": {"pos": target_pos, "r": target_r},
                    "walls": walls
                }
                with open("level.json", "w") as f:
                    json.dump(level_data, f)
                pygame.image.save(screen, "level.png")
                print("📸 Saved level.json + level.png!")
            if event.key == pygame.K_t:  # Toggle test
                test_mode = not test_mode
                if not test_mode:
                    balls = []
                    balls_used = 0
                    won = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            if test_mode:
                continue  # No edit in test
            if event.button == 1:  # Left: Select/drag
                if adding_line:
                    if add_start is None:
                        add_start = [snap(mx), snap(my)]
                    else:
                        walls.append([add_start, [snap(mx), snap(my)]])
                        adding_line = False
                        add_start = None
                else:
                    # Check start
                    if math.hypot(mx - start_pos[0], my - start_pos[1]) < 20:
                        selected = {'type': 'start'}
                    # Check target
                    elif math.hypot(mx - target_pos[0], my - target_pos[1]) < max(20, target_r + 5):
                        selected = {'type': 'target'}
                    # Check walls
                    else:
                        min_dist = 10
                        closest_wall = -1
                        closest_end = -1
                        for i, wall in enumerate(walls):
                            d1 = math.hypot(mx - wall[0][0], my - wall[0][1])
                            d2 = math.hypot(mx - wall[1][0], my - wall[1][1])
                            d_line = dist_to_line(mpos, wall[0], wall[1])
                            if d1 < min_dist:
                                min_dist = d1
                                closest_wall = i
                                closest_end = 0
                            if d2 < min_dist:
                                min_dist = d2
                                closest_wall = i
                                closest_end = 1
                            if d_line < min_dist and d_line < 5:  # Mid-line drag
                                min_dist = d_line
                                closest_wall = i
                                closest_end = -1  # Whole line
                        if closest_wall != -1:
                            selected = {'type': 'wall', 'idx': closest_wall, 'end': closest_end}
            if event.button == 3 and selected:  # Right: Delete
                if selected['type'] == 'wall':
                    del walls[selected['idx']]
                selected = None  # No delete start/target for now
        if event.type == pygame.MOUSEBUTTONUP:
            selected = None
        if event.type == pygame.MOUSEMOTION and selected and not test_mode:
            if selected['type'] == 'start':
                start_pos = [snap(mx), snap(my)]
            elif selected['type'] == 'target':
                target_pos = [snap(mx), snap(my)]
            elif selected['type'] == 'wall':
                wall = walls[selected['idx']]
                if selected['end'] == -1:  # Whole
                    dx = mx - (wall[0][0] + wall[1][0]) / 2
                    dy = my - (wall[0][1] + wall[1][1]) / 2
                    wall[0][0] += dx
                    wall[0][1] += dy
                    wall[1][0] += dx
                    wall[1][1] += dy
                else:
                    wall[selected['end']] = [snap(mx), snap(my)]

    if test_mode:
        # Launch (SPACE)
        if keys[pygame.K_SPACE] and current_time - launch_cooldown > 300:
            balls.append({'pos': start_pos[:], 'vel': [0.0, 0.0]})
            balls_used += 1
            launch_cooldown = current_time

        # Update balls
        new_balls = []
        for ball in balls:
            ball['vel'][0] += gravity[0] * dt
            ball['vel'][1] += gravity[1] * dt
            ball['pos'][0] += ball['vel'][0] * dt
            ball['pos'][1] += ball['vel'][1] * dt
            ball['vel'][0] *= drag_factor
            ball['vel'][1] *= drag_factor

            # Collisions
            for wall in walls:
                reflect_ball_over_line(ball['pos'], ball['vel'], wall[0], wall[1], ball_r)

            # Cull
            if (ball['pos'][0] < -50 or ball['pos'][0] > W + 50 or
                ball['pos'][1] > H + 50 or ball['pos'][1] < -50):
                continue

            # Target
            dx = ball['pos'][0] - target_pos[0]
            dy = ball['pos'][1] - target_pos[1]
            if math.hypot(dx, dy) < target_r + ball_r:
                won = True
                print(f"🎉 WIN with {balls_used} balls!")
                continue

            new_balls.append(ball)
        balls = new_balls

    # Draw
    screen.fill((15, 15, 30))
    # Grid (faint)
    for x in range(0, W, snap_grid):
        pygame.draw.line(screen, (25, 25, 50), (x, 0), (x, H))
    for y in range(0, H, snap_grid):
        pygame.draw.line(screen, (25, 25, 50), (0, y), (W, y))
    # Walls
    for wall in walls:
        pygame.draw.line(screen, (220, 220, 220), (int(wall[0][0]), int(wall[0][1])), (int(wall[1][0]), int(wall[1][1])), 8)
        pygame.draw.circle(screen, (255, 200, 200), (int(wall[0][0]), int(wall[0][1])), 5)
        pygame.draw.circle(screen, (255, 200, 200), (int(wall[1][0]), int(wall[1][1])), 5)
    # Start
    pygame.draw.circle(screen, (120, 120, 255), (int(start_pos[0]), int(start_pos[1])), 12)
    # Target
    pygame.draw.circle(screen, (80, 255, 120), (int(target_pos[0]), int(target_pos[1])), target_r)
    pygame.draw.circle(screen, (150, 255, 180), (int(target_pos[0]), int(target_pos[1])), target_r // 2)
    # Adding line preview
    if adding_line and add_start:
        pygame.draw.line(screen, (255, 255, 0), (int(add_start[0]), int(add_start[1])), (mx, my), 2)
    # Balls (test mode)
    if test_mode:
        for b in balls:
            pygame.draw.circle(screen, (255, 120, 120), (int(b['pos'][0]), int(b['pos'][1])), ball_r)
    # UI
    mode_text = "EDIT" if not test_mode else "TEST"
    text = font.render(f"Mode: {mode_text} | Balls: {balls_used}", True, (255, 255, 255))
    screen.blit(text, (10, 10))
    inst = smallfont.render("A: Add line (click-click) | Drag: Move | Right-click: Delete | T: Test | S: Snapshot | R: Reset balls", True, (180, 220, 255))
    screen.blit(inst, (10, 40))
    if won:
        wintext = font.render(f"WIN! {balls_used} balls", True, (255, 255, 120))
        screen.blit(wintext, (150, 250))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()