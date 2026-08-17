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

DONE_GLYPH = Glyph("○", "dim")

CONTENT_GLYPH = Glyph("•", "cyan")

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
    "hierarchy": (
        ("icon", "4ch"), ("content", "2ch"), ("id", "13ch"), ("title", "1fr"), ("role", "14ch"),
    ),
}

GLOBAL_SHORTCUTS = (
    ("↑↓", "move"),
    ("enter/→", "open"),
    ("tab", "backlog"),
    ("ctrl-u/ctrl-d", "scroll"),
    ("q", "quit"),
)

BACKLOG_SHORTCUTS = (
    ("↑↓", "move"),
    ("enter/→", "explore in tree"),
    ("f", "filter"),
    ("tab", "current work"),
    ("ctrl-u/ctrl-d", "scroll"),
    ("q", "quit"),
)

BACKLOG_EMPTY_SHORTCUTS = (
    ("tab", "current work"),
    ("q", "quit"),
)

BACKLOG_FILTERED_EMPTY_SHORTCUTS = (
    ("f", "filter"),
    ("tab", "current work"),
    ("q", "quit"),
)

HUB_SHORTCUTS = (
    ("[/]", "switch tab"),
    ("↑↓", "scroll"),
    ("enter/→", "open node"),
    ("esc/←", "back"),
    ("tab", "backlog"),
    ("q", "quit"),
)
