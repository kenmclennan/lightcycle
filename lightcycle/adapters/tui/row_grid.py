from dataclasses import dataclass

from textual.geometry import Size

GLYPH_WIDTHS = {"cursor": 2, "icon": 4, "content": 2}
ATOMIC_COLUMNS = frozenset({"id", "project", "step", "role", "type", "time"})
FLEXIBLE_COLUMNS = frozenset({"title", "value"})
FLEXIBLE_MINIMUM = 24


def column_kind(name):
    if name in GLYPH_WIDTHS:
        return "glyph"
    if name in ATOMIC_COLUMNS:
        return "atomic"
    if name in FLEXIBLE_COLUMNS:
        return "flexible"
    raise KeyError(name)


def classify_grid(columns):
    glyphs, atomics, flexibles = [], [], []
    for name in columns:
        kind = column_kind(name)
        if kind == "glyph":
            glyphs.append(name)
        elif kind == "atomic":
            atomics.append(name)
        else:
            flexibles.append(name)
    return glyphs, atomics, flexibles


def atomic_column_width(values):
    lengths = [len(value) for value in values if value]
    return max(lengths) if lengths else 0


@dataclass(frozen=True)
class GridLayout:
    atomic_widths: dict
    flexible_width: int
    stacked: bool
    floor: bool
    floor_width: int


def compute_layout(row_budget, glyph_columns, atomic_values, indent):
    glyph_total = sum(GLYPH_WIDTHS[name] for name in glyph_columns)
    atomic_widths = {
        name: max(1, atomic_column_width(values)) for name, values in atomic_values.items()
    }
    atomic_total = sum(atomic_widths.values())
    first_line_width = glyph_total + atomic_total
    floor_width = max(first_line_width, indent + FLEXIBLE_MINIMUM)
    if row_budget is None:
        return GridLayout(atomic_widths, 1, False, False, floor_width)
    if row_budget < floor_width:
        return GridLayout(atomic_widths, FLEXIBLE_MINIMUM, False, True, floor_width)
    remaining = row_budget - first_line_width
    if remaining < FLEXIBLE_MINIMUM:
        return GridLayout(atomic_widths, row_budget - indent, True, False, floor_width)
    return GridLayout(atomic_widths, remaining, False, False, floor_width)


def row_budget_for(table, num_columns):
    padding = 2 * table.cell_padding * num_columns
    return table.size.width - padding


def floor_message(layout, table, num_columns):
    padding = 2 * table.cell_padding * num_columns
    chrome = table.screen.outer_size.width - table.screen.size.width
    needed = layout.floor_width + padding + chrome
    return "Widen the terminal to at least %d columns to show this list." % needed


def apply_widths(table, widths):
    for key, new_width in widths.items():
        column = table.columns.get(key)
        if column is None or column.width == new_width:
            continue
        delta = new_width - column.width
        column.width = new_width
        virtual_width, virtual_height = table.virtual_size
        table.virtual_size = Size(virtual_width + delta, virtual_height)
    table._clear_caches()
    table.refresh()
