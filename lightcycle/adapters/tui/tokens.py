BG = "#0c0c0f"
PANEL = "#101014"
BORDER = "#3a3a42"
TEXT = "#d8d8dc"
DIM = "#6e6e78"
CYAN = "#5fd7e0"
AMBER = "#e0a95f"
RED = "#e05f6b"
SELECTED_BG = "#1c2a2c"

STATE_GLYPHS = {
    "attention": (("●", RED),),
    "attention_blocked": (("●", RED), ("⛓", AMBER)),
    "active": (("▸", CYAN),),
    "queued": (("○", DIM),),
}

PRIORITY_LIST_GRID = (
    ("cursor", 2), ("icon", 4), ("id", 9), ("project", 10),
    ("title", "1fr"), ("step", 16), ("time", 8),
)
BACKLOG_GRID = (
    ("cursor", 2), ("id", 9), ("project", 10), ("title", "1fr"),
)
