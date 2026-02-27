# stock_shapes.py - Parameterized component library for K-Maze
import math


def make_funnel(width=120, height=100, neck_width=30):
    """Funnel: wide opening narrows to a gap. Ball enters top, exits bottom."""
    half_w = width / 2
    half_neck = neck_width / 2
    walls = [
        [[-half_w, 0], [-half_neck, height]],   # left slant
        [[half_w, 0], [half_neck, height]],      # right slant
    ]
    return {
        "name": f"funnel_{width}x{height}",
        "walls": walls,
        "ks": [],
        "entry": {"type": "line", "a": [-half_w, 0], "b": [half_w, 0]},
        "exit":  {"type": "line", "a": [-half_neck, height], "b": [half_neck, height]},
        "bbox":  [-half_w, 0, half_w, height],
        "tags":  ["vertical", "funnel", "collector"],
    }


def make_trampoline(width=150, wall_angle=15, k_boost=True):
    """Trampoline: V-shaped surface + optional K. Ball enters top, bounces back up."""
    angle_rad = math.radians(wall_angle)
    rise = width / 2 * math.tan(angle_rad)

    walls = [
        [[0, rise], [width / 2, 0]],           # left arm (slopes down to center)
        [[width / 2, 0], [width, rise]],        # right arm (slopes up from center)
    ]
    ks = []
    if k_boost:
        ks.append({"center": [width / 2, -15], "angle": 0.0})

    return {
        "name": f"trampoline_{width}",
        "walls": walls,
        "ks": ks,
        "entry": {"type": "line", "a": [0, -30], "b": [width, -30]},
        "exit":  {"type": "line", "a": [0, -30], "b": [width, -30]},
        "bbox":  [0, -30, width, rise],
        "tags":  ["vertical", "trampoline", "redirect"],
    }


def make_cannon(length=120, angle_deg=-60, k_at_base=True):
    """Cannon: narrow tube angled upward with K at closed end to launch ball."""
    angle_rad = math.radians(angle_deg)
    tube_width = 30
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    perp_x = -sin_a * tube_width / 2
    perp_y = cos_a * tube_width / 2

    end_x = length * cos_a
    end_y = length * sin_a

    walls = [
        [[perp_x, perp_y], [end_x + perp_x, end_y + perp_y]],       # left wall
        [[-perp_x, -perp_y], [end_x - perp_x, end_y - perp_y]],     # right wall
        [[end_x + perp_x, end_y + perp_y],
         [end_x - perp_x, end_y - perp_y]],                          # back wall
    ]
    ks = []
    if k_at_base:
        ks.append({"center": [end_x * 0.85, end_y * 0.85],
                    "angle": angle_rad + math.pi})

    all_x = [0, perp_x, -perp_x, end_x + perp_x, end_x - perp_x]
    all_y = [0, perp_y, -perp_y, end_y + perp_y, end_y - perp_y]

    return {
        "name": f"cannon_{angle_deg}deg",
        "walls": walls,
        "ks": ks,
        "entry": {"type": "line", "a": [perp_x, perp_y], "b": [-perp_x, -perp_y]},
        "exit":  {"type": "line", "a": [perp_x, perp_y], "b": [-perp_x, -perp_y]},
        "bbox":  [min(all_x), min(all_y), max(all_x), max(all_y)],
        "tags":  ["launcher", "cannon"],
    }


def make_bouncy_room(width=150, height=150, opening_width=40,
                     openings="top_bottom", num_ks=1):
    """Enclosed room with openings and K shapes inside."""
    half_open = opening_width / 2
    cx, cy = width / 2, height / 2
    walls = []

    if openings == "top_bottom":
        walls.append([[0, 0], [cx - half_open, 0]])
        walls.append([[cx + half_open, 0], [width, 0]])
        walls.append([[0, height], [cx - half_open, height]])
        walls.append([[cx + half_open, height], [width, height]])
        walls.append([[0, 0], [0, height]])
        walls.append([[width, 0], [width, height]])
        entry = {"type": "line", "a": [cx - half_open, 0], "b": [cx + half_open, 0]}
        exit_ = {"type": "line", "a": [cx - half_open, height], "b": [cx + half_open, height]}
    elif openings == "left_right":
        walls.append([[0, 0], [width, 0]])
        walls.append([[0, height], [width, height]])
        walls.append([[0, 0], [0, cy - half_open]])
        walls.append([[0, cy + half_open], [0, height]])
        walls.append([[width, 0], [width, cy - half_open]])
        walls.append([[width, cy + half_open], [width, height]])
        entry = {"type": "line", "a": [0, cy - half_open], "b": [0, cy + half_open]}
        exit_ = {"type": "line", "a": [width, cy - half_open], "b": [width, cy + half_open]}
    else:  # top_right
        walls.append([[0, 0], [cx - half_open, 0]])
        walls.append([[cx + half_open, 0], [width, 0]])
        walls.append([[0, height], [width, height]])
        walls.append([[0, 0], [0, height]])
        walls.append([[width, 0], [width, cy - half_open]])
        walls.append([[width, cy + half_open], [width, height]])
        entry = {"type": "line", "a": [cx - half_open, 0], "b": [cx + half_open, 0]}
        exit_ = {"type": "line", "a": [width, cy - half_open], "b": [width, cy + half_open]}

    ks = []
    for i in range(num_ks):
        kx = width * (i + 1) / (num_ks + 1)
        ky = height / 2
        ks.append({"center": [kx, ky], "angle": 0.0})

    return {
        "name": f"bouncy_room_{openings}",
        "walls": walls,
        "ks": ks,
        "entry": entry,
        "exit": exit_,
        "bbox": [0, 0, width, height],
        "tags": ["room", "bouncy", "complex"],
    }


def make_ramp(width=200, height=80, channel_gap=35, direction="left_to_right"):
    """Ramp/slide: channel with two parallel walls the ball rolls through."""
    # Normal vector perpendicular to the ramp surface (pointing "up" from the slope)
    ramp_len = math.hypot(width, height)
    nx = -height / ramp_len * channel_gap
    ny = width / ramp_len * channel_gap

    if direction == "left_to_right":
        walls = [
            [[0, 0], [width, height]],                       # bottom surface
            [[nx, ny], [width + nx, height + ny]],            # top surface (parallel)
            [[0, 0], [nx, ny]],                               # left cap
        ]
        entry = {"type": "line", "a": [0, 0], "b": [nx, ny]}
        exit_ = {"type": "line", "a": [width, height], "b": [width + nx, height + ny]}
    else:
        walls = [
            [[0, height], [width, 0]],                       # bottom surface
            [[nx, height + ny], [width + nx, ny]],            # top surface
            [[width, 0], [width + nx, ny]],                   # right cap
        ]
        entry = {"type": "line", "a": [width, 0], "b": [width + nx, ny]}
        exit_ = {"type": "line", "a": [0, height], "b": [nx, height + ny]}

    all_x = [p[0] for w in walls for p in w]
    all_y = [p[1] for w in walls for p in w]

    return {
        "name": f"ramp_{direction}",
        "walls": walls,
        "ks": [],
        "entry": entry,
        "exit": exit_,
        "bbox": [min(all_x), min(all_y), max(all_x), max(all_y)],
        "tags": ["horizontal", "ramp", "slide"],
    }


def make_gate(width=60, gap=25, height=80):
    """Narrow passage: two walls forming a tight gap. Tests precision."""
    half_w = width / 2
    half_gap = gap / 2
    walls = [
        [[-half_w, 0], [-half_gap, 0]],
        [[half_gap, 0], [half_w, 0]],
        [[-half_w, height], [-half_gap, height]],
        [[half_gap, height], [half_w, height]],
        [[-half_w, 0], [-half_w, height]],
        [[half_w, 0], [half_w, height]],
        [[-half_gap, 0], [-half_gap, height]],
        [[half_gap, 0], [half_gap, height]],
    ]
    return {
        "name": f"gate_{gap}px",
        "walls": walls,
        "ks": [],
        "entry": {"type": "line", "a": [-half_gap, 0], "b": [half_gap, 0]},
        "exit":  {"type": "line", "a": [-half_gap, height], "b": [half_gap, height]},
        "bbox":  [-half_w, 0, half_w, height],
        "tags":  ["vertical", "gate", "precision"],
    }


# --- Utilities ---

def translate_component(component, dx, dy):
    """Return a new component with all coordinates offset by (dx, dy)."""
    def offset(pt):
        return [pt[0] + dx, pt[1] + dy]

    return {
        "name": component["name"],
        "walls": [[offset(p) for p in wall] for wall in component["walls"]],
        "ks": [{"center": offset(k["center"]), "angle": k["angle"]}
               for k in component["ks"]],
        "entry": {"type": "line", "a": offset(component["entry"]["a"]),
                  "b": offset(component["entry"]["b"])},
        "exit":  {"type": "line", "a": offset(component["exit"]["a"]),
                  "b": offset(component["exit"]["b"])},
        "bbox": [component["bbox"][0] + dx, component["bbox"][1] + dy,
                 component["bbox"][2] + dx, component["bbox"][3] + dy],
        "tags": component["tags"][:],
    }


# --- Registry ---

COMPONENT_REGISTRY = {
    "funnel":          {"fn": make_funnel,       "defaults": {}},
    "funnel_wide":     {"fn": make_funnel,       "defaults": {"width": 180, "neck_width": 35}},
    "trampoline":      {"fn": make_trampoline,   "defaults": {}},
    "trampoline_flat": {"fn": make_trampoline,   "defaults": {"wall_angle": 8}},
    "cannon_up":       {"fn": make_cannon,       "defaults": {"angle_deg": -60}},
    "cannon_side":     {"fn": make_cannon,       "defaults": {"angle_deg": -15}},
    "bouncy_room":     {"fn": make_bouncy_room,  "defaults": {}},
    "bouncy_room_lr":  {"fn": make_bouncy_room,  "defaults": {"openings": "left_right"}},
    "bouncy_room_tr":  {"fn": make_bouncy_room,  "defaults": {"openings": "top_right"}},
    "ramp_lr":         {"fn": make_ramp,         "defaults": {}},
    "ramp_rl":         {"fn": make_ramp,         "defaults": {"direction": "right_to_left"}},
    "gate":            {"fn": make_gate,         "defaults": {}},
    "gate_tight":      {"fn": make_gate,         "defaults": {"gap": 22}},
}


def get_component(name, **overrides):
    """Get a component by registry name, optionally overriding parameters."""
    if name not in COMPONENT_REGISTRY:
        return None
    entry = COMPONENT_REGISTRY[name]
    params = {**entry["defaults"], **overrides}
    return entry["fn"](**params)


def list_components():
    """Return list of all registered component names."""
    return list(COMPONENT_REGISTRY.keys())


# --- Backward compatibility for editor.py ---

STOCK_SHAPES = []
for _name in COMPONENT_REGISTRY:
    _comp = get_component(_name)
    if _comp:
        STOCK_SHAPES.append({
            "name": _name,
            "walls": _comp["walls"],
            "ks": _comp.get("ks", []),
        })


def get_shape_by_name(name):
    """Return shape dict by name, or None."""
    for shape in STOCK_SHAPES:
        if shape['name'] == name:
            return shape
    return None
