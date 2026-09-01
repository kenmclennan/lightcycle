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

MODAL_OVERLAY_ALPHA = 0.72

STATE_GLYPHS = {
    "needs-attention": Glyph("●", "red"),
    "gate": Glyph("●", "amber"),
    "escalation": Glyph("▲", "red"),
    "active": Glyph("◆", "cyan"),
    "queued": Glyph("○", "dim"),
}

ACTIVE_GLYPH_FRAMES = ("◇", "◈", "◆", "◈")
ACTIVE_GLYPH_REST_INDEX = 2
ACTIVE_GLYPH_TICKS_PER_SECOND = 8


def next_active_glyph_frame(index):
    return (index + 1) % len(ACTIVE_GLYPH_FRAMES)


DEPENDENCY_BLOCKED_EXTRA_GLYPH = Glyph("⛓", "amber")

DONE_GLYPH = Glyph("○", "dim")

CONTENT_GLYPH = Glyph("•", "cyan")

FOOTER_GLYPHS = {
    "pool-running": Glyph("●", "cyan"),
    "pool-stopped": Glyph("○", "dim"),
    "claude-available": Glyph("●", "cyan"),
    "claude-unavailable": Glyph("⊘", "red"),
    "claude-probing": Glyph("◐", "amber"),
    "upgrade-available": Glyph("⬆", "amber"),
}

CURSOR_GLYPH = Glyph("❯", "cyan")

COLUMN_GRIDS = {
    "priority-list": ("cursor", "icon", "id", "project", "title", "step", "time"),
    "backlog": ("cursor", "id", "project", "title"),
    "hierarchy": ("icon", "content", "id", "title", "role"),
    "artifacts": ("type", "value"),
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
    ("b", "open blocker"),
    ("esc/←", "back"),
    ("tab", "backlog"),
    ("q", "quit"),
)

TEXT_ARTIFACT_SHORTCUTS = (
    ("↑↓", "scroll"),
    ("ctrl-u/ctrl-d", "page"),
    ("esc/←", "back to artifacts"),
    ("tab", "backlog"),
    ("q", "quit"),
)

LIST_ARTIFACT_SHORTCUTS = (
    ("↑↓", "scroll"),
    ("esc/←", "back to artifacts"),
    ("tab", "backlog"),
    ("q", "quit"),
)
