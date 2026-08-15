from collections import namedtuple

Glyph = namedtuple("Glyph", ["glyph", "colour"])

COLOURS = {
    "bg": "#0c0c0f",
    "panel": "#101014",
    "border": "#3a3a42",
    "text": "#d8d8dc",
    "dim": "#6e6e78",
    "cyan": "#5fd7e0",
    "amber": "#e0a95f",
    "red": "#e05f6b",
    "selected-bg": "#1c2a2c",
}

STATE_GLYPHS = {
    "needs-attention": Glyph("●", "red"),
    "active": Glyph("▸", "cyan"),
    "queued": Glyph("○", "dim"),
}

DEPENDENCY_BLOCKED_EXTRA_GLYPH = Glyph("⛓", "amber")

FOOTER_GLYPHS = {
    "pool-running": Glyph("●", "cyan"),
    "pool-stopped": Glyph("○", "dim"),
    "claude-available": Glyph("●", "cyan"),
    "claude-unavailable": Glyph("⊘", "red"),
    "upgrade-available": Glyph("⬆", "amber"),
}

CURSOR_GLYPH = Glyph("❯", "cyan")

COLUMN_GRIDS = {
    "priority-list": (
        ("cursor", "2ch"), ("icon", "4ch"), ("id", "9ch"), ("project", "10ch"),
        ("title", "1fr"), ("step", "16ch"), ("time", "8ch"),
    ),
    "backlog": (
        ("cursor", "2ch"), ("id", "9ch"), ("project", "10ch"), ("title", "1fr"),
    ),
}

GLOBAL_SHORTCUTS = (
    ("↑↓", "move"),
    ("enter/→", "open"),
    ("tab", "backlog"),
    ("ctrl-u/ctrl-d", "scroll"),
    ("q", "quit"),
)
