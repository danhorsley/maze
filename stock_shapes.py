# stock_shapes.py - Pre-defined maze elements for K-Maze Editor
# Each shape: {'name': str, 'walls': list of [[x1,y1], [x2,y2]] relative to [0,0]}

STOCK_SHAPES = [
    {
        'name': 'corridor_h',  # Horizontal corridor (200px wide, 50px high gap)
        'walls': [
            [[0, 0], [200, 0]],     # top
            [[0, 50], [200, 50]],   # bottom
        ]
    },
    {
        'name': 'corridor_v',  # Vertical corridor (50px wide, 200px high gap)
        'walls': [
            [[0, 0], [0, 200]],     # left
            [[50, 0], [50, 200]],   # right
        ]
    },
    {
        'name': 'pipe',  # Narrow vertical pipe (30px wide, 150px high, with slight flare)
        'walls': [
            [[0, 0], [0, 150]],     # left straight
            [[30, 0], [30, 150]],   # right straight
            [[-10, 0], [0, 10]],    # top left flare
            [[30, 0], [40, 10]],    # top right flare
            [[-10, 150], [0, 140]], # bottom left flare
            [[30, 150], [40, 140]], # bottom right flare
        ]
    },
    {
        'name': 'funnel',  # Inverted triangle funnel (wide top to narrow bottom)
        'walls': [
            [[-50, 0], [50, 0]],    # top wide
            [[-50, 0], [0, 100]],   # left slant
            [[50, 0], [0, 100]],    # right slant
        ]
    },
    {
        'name': 'room',  # Square open room (150x150, optional bouncy if you add flag)
        'walls': [
            [[0, 0], [150, 0]],     # top
            [[0, 0], [0, 150]],     # left
            [[150, 0], [150, 150]], # right
            [[0, 150], [150, 150]], # bottom
        ]
    },
]

def get_shape_by_name(name):
    """Return shape dict by name, or None."""
    for shape in STOCK_SHAPES:
        if shape['name'] == name:
            return shape
    return None