import pygame
import math
import json
import sys
from physics import (
    K_REL_POINTS, GRAVITY, DRAG, BALL_R, DT, RESTITUTION, K_RESTITUTION,
    PLAYFIELD_W, PLAYFIELD_H,
    rotate_points, reflect_ball_over_line,
)

# Defaults
start_pos = [90.0, 60.0]
target_pos = [680, 530]
target_r = 25
walls = [
    [[0, 0], [0, 600]],
    [[800, 0], [800, 600]],
    [[0, 600], [800, 600]],
    [[170, 50], [170, 400]],
    [[420, 150], [420, 550]],
]

# Try to load saved level (overrides defaults)
try:
    with open("level.json", "r") as f:
        data = json.load(f)
        start_pos = data["start"]
        target_pos = data["target"]["pos"]
        target_r = data["target"]["r"]
        walls = data["walls"]
except FileNotFoundError:
    pass

pygame.init()
W, H = PLAYFIELD_W, PLAYFIELD_H
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("K-Maze Proto: Fewest Balls to Target")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 42)
smallfont = pygame.font.Font(None, 24)

# Globals
k_center = [140.0, 250.0]
k_angle = 0.0
balls = []
balls_used = 0
won = False
launch_cooldown = 0
rotating = False
prev_mouse_angle = 0.0

running = True
while running:
    current_time = pygame.time.get_ticks()
    keys = pygame.key.get_pressed()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
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
        balls.append({'pos': start_pos[:], 'vel': [0.0, 0.0]})
        balls_used += 1
        launch_cooldown = current_time

    # Update balls
    rot_k = rotate_points(K_REL_POINTS, k_angle, k_center)
    k_segs = [(rot_k[i], rot_k[i + 1]) for i in range(len(rot_k) - 1)]

    new_balls = []
    for ball in balls:
        ball['vel'][0] += GRAVITY[0] * DT
        ball['vel'][1] += GRAVITY[1] * DT
        ball['pos'][0] += ball['vel'][0] * DT
        ball['pos'][1] += ball['vel'][1] * DT
        ball['vel'][0] *= DRAG
        ball['vel'][1] *= DRAG

        # Wall collisions (standard restitution)
        for seg_start, seg_end in walls:
            reflect_ball_over_line(ball['pos'], ball['vel'], seg_start, seg_end, BALL_R)

        # K collisions (bouncier)
        for seg_start, seg_end in k_segs:
            reflect_ball_over_line(ball['pos'], ball['vel'], seg_start, seg_end, BALL_R, K_RESTITUTION)

        # Out of bounds = dead (no bounce off screen edges)
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

    # Draw
    screen.fill((15, 15, 30))
    # Walls
    for s1, s2 in walls:
        pygame.draw.line(screen, (220, 220, 220), (int(s1[0]), int(s1[1])), (int(s2[0]), int(s2[1])), 8)
    # K (thick glowy)
    pygame.draw.lines(screen, (100, 255, 150), True, rot_k, 10)
    pygame.draw.lines(screen, (0, 255, 255), True, rot_k, 6)
    pygame.draw.circle(screen, (255, 255, 0), (int(k_center[0]), int(k_center[1])), 6)
    # Balls
    for b in balls:
        pygame.draw.circle(screen, (255, 120, 120), (int(b['pos'][0]), int(b['pos'][1])), BALL_R)
    # Target
    pygame.draw.circle(screen, (80, 255, 120), (int(target_pos[0]), int(target_pos[1])), target_r)
    pygame.draw.circle(screen, (150, 255, 180), (int(target_pos[0]), int(target_pos[1])), target_r // 2)
    # Start pos
    pygame.draw.circle(screen, (120, 120, 120), (int(start_pos[0]), int(start_pos[1])), 7)
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
