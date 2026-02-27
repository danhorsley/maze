import random
import json
import math

def backtracker_maze(width=25, height=20, cell_size=25):
    """Recursive DFS: grid → walls list."""
    grid = [[0]*width for _ in range(height)]  # 0=unvisited
    stack = [(1,1)]  # Start cell
    grid[1][1] = 1
    dirs = [(0,1,'h'), (1,0,'v'), (0,-1,'h'), (-1,0,'v')]  # N,S,E,W? Wait, adjust
    
    while stack:
        x, y = stack[-1]
        unvis = []
        for dx, dy, wall_type in dirs:
            nx = x + dx
            ny = y + dy
            if 1 <= nx < width - 1 and 1 <= ny < height - 1 and grid[ny][nx] == 0:
                unvis.append((nx, ny, wall_type))

        if unvis:
            nx, ny, wall_type = random.choice(unvis)
            # Carve the wall between (x,y) and (nx,ny)
            # For example:
            if wall_type == 'h':
                mid_x = (x + nx) // 2
                mid_y = y
                # Remove horizontal wall at mid
            elif wall_type == 'v':
                mid_x = x
                mid_y = (y + ny) // 2
                # Remove vertical wall at mid
            stack.append((nx, ny))
            grid[ny][nx] = 1  # Mark visited
        else:
            stack.pop()
    
    # Convert to walls (horiz/vert lines)
    walls = []
    for y in range(height):
        for x in range(width):
            if grid[y][x] == 0: continue  # Skip paths
            cx, cy = x*cell_size + cell_size//2, y*cell_size + cell_size//2
            # Add perimeter walls around cells (optimize: only between unvisited)
            # ... (full: check neighbors, add line if wall present)
    
    return {'walls': walls, 'start': [50,50], 'target': [700,500]}  # Tune

# Gen 50
courses = []
for i in range(50):
    random.seed(i)  # Reproducible
    courses.append(backtracker_maze(random.randint(20,30), random.randint(15,25)))
with open('maze_courses.json', 'w') as f:
    json.dump(courses, f, indent=2)
print("Gen'd 50 courses! Load in editor.")