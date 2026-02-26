import pygame
import math
import sys


try:
    with open("level.json", "r") as f:
        data = json.load(f)
        start_pos = data["start"]  # Add this
        target_pos = data["target"]["pos"]
        target_r = data["target"]["r"]
        walls = data["walls"]
except FileNotFoundError:
    pass  # Use defaults
pygame.init()
W, H = 800, 600
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("K-Maze Proto: Fewest Balls to Target")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 42)
smallfont = pygame.font.Font(None, 24)

# Globals
k_center = [140.0, 250.0]
k_points = [[0, -45], [0, 45], [30, 30], [0, 0], [30, -30], [0, -45]]  # FIXED K!
k_angle = 0.0
balls = []
balls_used = 0
won = False
launch_cooldown = 0
rotating = False
prev_mouse_angle = 0.0

gravity = [0.0, 400.0]
drag = 0.995
ball_r = 10
dt = 1.0 / 60.0

walls = [  # Maze: left chute (0-170), K deflects right chute (170+), target bottom-right
    [[0, 0], [0, 600]],  # left wall
    [[800, 0], [800, 600]],  # right wall
    [[0, 600], [800, 600]],  # bottom
    [[170, 50], [170, 400]],  # left chute RIGHT wall (K protrudes)
    [[420, 150], [420, 550]],  # right chute LEFT wall
]

target_pos = [680, 530]
target_r = 25

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

running = True
while running:
    current_time = pygame.time.get_ticks()
    keys = pygame.key.get_pressed()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:  # Reset
                balls = []
                balls_used = 0
                won = False
                k_angle = 0.0
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
    if keys[pygame.K_SPACE] and current_time - launch_cooldown > 300:
        balls.append({'pos': [90.0, 60.0], 'vel': [0.0, 0.0]})
        balls_used += 1
        launch_cooldown = current_time

    # Update balls
    rot_k = rotate_points(k_points, k_angle, k_center)
    k_segs = [(rot_k[i], rot_k[i + 1]) for i in range(len(rot_k) - 1)]
    all_segs = walls + k_segs

    new_balls = []
    for ball in balls:
        ball['vel'][0] += gravity[0] * dt
        ball['vel'][1] += gravity[1] * dt
        ball['pos'][0] += ball['vel'][0] * dt
        ball['pos'][1] += ball['vel'][1] * dt
        ball['vel'][0] *= drag
        ball['vel'][1] *= drag

        # Collisions
        for seg_start, seg_end in all_segs:
            reflect_ball_over_line(ball['pos'], ball['vel'], seg_start, seg_end, ball_r)

        # Bounds cull
        if (ball['pos'][0] < -50 or ball['pos'][0] > 850 or
            ball['pos'][1] > 650 or ball['pos'][1] < -50):
            continue

        # Target hit?
        dx = ball['pos'][0] - target_pos[0]
        dy = ball['pos'][1] - target_pos[1]
        if math.hypot(dx, dy) < target_r + ball_r:
            won = True
            print(f"🎉 WIN with {balls_used} balls!")
            continue  # Remove hitter

        new_balls.append(ball)
    balls = new_balls

    # Draw
    screen.fill((15, 15, 30))
    # Walls
    for s1, s2 in walls:
        pygame.draw.line(screen, (220, 220, 220), (int(s1[0]), int(s1[1])), (int(s2[0]), int(s2[1])), 8)
    # K (thick glowy)
    pygame.draw.lines(screen, (100, 255, 150), True, rot_k, 10)
    pygame.draw.lines(screen, (0, 255, 255), True, rot_k, 6)
    pygame.draw.circle(screen, (255, 255, 0), (int(k_center[0]), int(k_center[1])), 6)  # Rotate grip
    # Balls
    for b in balls:
        pygame.draw.circle(screen, (255, 120, 120), (int(b['pos'][0]), int(b['pos'][1])), ball_r)
    # Target
    pygame.draw.circle(screen, (80, 255, 120), (int(target_pos[0]), int(target_pos[1])), target_r)
    pygame.draw.circle(screen, (150, 255, 180), (int(target_pos[0]), int(target_pos[1])), target_r // 2)
    # Start pos
    pygame.draw.circle(screen, (120, 120, 120), (90, 60), 7)
    # UI
    text = font.render(f"Balls: {balls_used}", True, (255, 255, 255))
    screen.blit(text, (10, 10))
    inst = smallfont.render("SPACE: Launch | Drag yellow dot on K | R: Reset", True, (180, 220, 255))
    screen.blit(inst, (10, 40))
    if won:
        wintext = font.render(f"WIN! {balls_used} balls", True, (255, 255, 120))
        screen.blit(wintext, (150, 250))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()