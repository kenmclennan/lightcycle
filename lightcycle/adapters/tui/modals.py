
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from lightcycle.adapters.tui.design_system import (
    COLOURS,
    CURSOR_GLYPH,
    MODAL_OVERLAY_ALPHA,
)
from lightcycle.adapters.tui.row_grid import (
    atomic_column_width,
)

PICKER_CANCELLED = object()
POOL_PROMPT_CANCELLED = object()
POOL_PROMPT_STOP = "stop"
POOL_PROMPT_DRAIN = "drain"
POOL_PROMPT_QUIT_LEAVE = "quit-leave"
POOL_PROMPT_QUIT_STOP = "quit-stop"
POOL_PROMPT_MIN_WIDTH = 52


PICKER_MIN_WIDTH = 40
PICKER_BORDER_WIDTH = 2
PICKER_PADDING_WIDTH = 2
PICKER_CURSOR_PREFIX_WIDTH = 2
PICKER_COLUMN_GAP = 1


class ProjectFilterPicker(ModalScreen):
    CSS = f"""
    ProjectFilterPicker {{
        align: center top;
        background: {COLOURS["bg"]} {int(MODAL_OVERLAY_ALPHA * 100)}%;
        border: none;
    }}
    #picker {{
        width: {PICKER_MIN_WIDTH};
        height: auto;
        margin-top: 4;
        background: {COLOURS["panel"]};
        border: solid {COLOURS["cyan"]};
    }}
    #picker-head {{
        height: 2;
        padding: 0 1;
        color: {COLOURS["cyan"]};
        border-bottom: solid {COLOURS["border"]};
    }}
    .picker-option {{
        height: 1;
        padding: 0 1;
    }}
    #picker-option-label {{
        width: 1fr;
    }}
    .picker-option-count {{
        content-align: right middle;
        color: {COLOURS["dim"]};
    }}
    .picker-option-selected {{
        background: {COLOURS["selected-bg"]};
    }}
    #picker-foot {{
        height: 2;
        padding: 0 1;
        color: {COLOURS["dim"]};
        border-top: solid {COLOURS["border"]};
    }}
    """

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "apply", "Apply", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, options, heading="Filter by project"):
        super().__init__()
        self._options = options
        self._heading = heading
        self._index = 0
        self._count_width = max(
            1, atomic_column_width([str(count) for _, _, count in options])
        )
        label_width = atomic_column_width([label for _, label, _ in options])
        computed_width = (
            PICKER_BORDER_WIDTH
            + PICKER_PADDING_WIDTH
            + PICKER_CURSOR_PREFIX_WIDTH
            + label_width
            + PICKER_COLUMN_GAP
            + self._count_width
        )
        self._picker_width = max(computed_width, PICKER_MIN_WIDTH)

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static(self._heading, id="picker-head")
            for index, (_, label, count) in enumerate(self._options):
                yield PickerOption(label, count, self._count_width, id="picker-option-%d" % index)
            yield Static("↑↓ move · enter apply · esc cancel", id="picker-foot")

    def on_mount(self) -> None:
        self.query_one("#picker").styles.width = self._picker_width
        self._paint_highlight()

    def _paint_highlight(self) -> None:
        for index, option in enumerate(self.query(PickerOption)):
            option.set_highlighted(index == self._index)

    def action_move_down(self) -> None:
        self._index = min(self._index + 1, len(self._options) - 1)
        self._paint_highlight()

    def action_move_up(self) -> None:
        self._index = max(self._index - 1, 0)
        self._paint_highlight()

    def action_apply(self) -> None:
        self.dismiss(self._options[self._index][0])

    def action_cancel(self) -> None:
        self.dismiss(PICKER_CANCELLED)


class PoolPromptScreen(ModalScreen):
    CSS = f"""
    PoolPromptScreen {{
        align: center top;
        background: {COLOURS["bg"]} {int(MODAL_OVERLAY_ALPHA * 100)}%;
        border: none;
    }}
    #pool-prompt {{
        width: {POOL_PROMPT_MIN_WIDTH};
        height: auto;
        margin-top: 4;
        background: {COLOURS["panel"]};
        border: solid {COLOURS["cyan"]};
    }}
    #pool-prompt-head {{
        height: 1;
        padding: 0 1;
        color: {COLOURS["cyan"]};
    }}
    #pool-prompt-body {{
        height: auto;
        padding: 0 1;
        color: {COLOURS["text"]};
        border-bottom: solid {COLOURS["border"]};
    }}
    .pool-prompt-option {{
        height: 1;
        padding: 0 1;
    }}
    .pool-prompt-option-selected {{
        background: {COLOURS["selected-bg"]};
    }}
    #pool-prompt-foot {{
        height: 2;
        padding: 0 1;
        color: {COLOURS["dim"]};
        border-top: solid {COLOURS["border"]};
    }}
    """

    BINDINGS = [
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
        Binding("enter", "apply", "Apply", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, heading, body, options):
        super().__init__()
        self._heading = heading
        self._body = body
        self._options = options
        self._index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="pool-prompt"):
            yield Static(self._heading, id="pool-prompt-head")
            yield Static(self._body, id="pool-prompt-body")
            for index, (_, label) in enumerate(self._options):
                yield Static(label, classes="pool-prompt-option", id="pool-prompt-option-%d" % index)
            yield Static("↑↓ move · enter apply · esc cancel", id="pool-prompt-foot")

    def on_mount(self) -> None:
        self._paint_highlight()

    def _paint_highlight(self) -> None:
        for index, option in enumerate(self.query(".pool-prompt-option")):
            option.set_class(index == self._index, "pool-prompt-option-selected")
            option.update("%s %s" % (
                CURSOR_GLYPH.glyph if index == self._index else " ", self._options[index][1]))

    def action_move_down(self) -> None:
        self._index = min(self._index + 1, len(self._options) - 1)
        self._paint_highlight()

    def action_move_up(self) -> None:
        self._index = max(self._index - 1, 0)
        self._paint_highlight()

    def action_apply(self) -> None:
        self.dismiss(self._options[self._index][0])

    def action_cancel(self) -> None:
        self.dismiss(POOL_PROMPT_CANCELLED)


def pool_prompt_body(worker_count):
    if worker_count == 0:
        return "No workers are running."
    return "%d worker%s running; %s steps will be reclaimed and re-run." % (
        worker_count, "" if worker_count == 1 else "s",
        "its" if worker_count == 1 else "their")




class PickerOption(Horizontal):
    def __init__(self, label, count, count_width, *, id=None):
        super().__init__(id=id, classes="picker-option")
        self.label_text = label
        self.count = count
        self.count_width = count_width

    def compose(self) -> ComposeResult:
        yield Static(id="picker-option-label")
        yield Static(str(self.count), classes="picker-option-count")

    def on_mount(self) -> None:
        self.query_one(".picker-option-count", Static).styles.width = self.count_width

    def set_highlighted(self, highlighted) -> None:
        cursor = Text(
            "%s " % CURSOR_GLYPH.glyph, style=COLOURS[CURSOR_GLYPH.colour]
        ) if highlighted else Text("  ")
        label = cursor + Text(self.label_text, style=COLOURS["text"])
        self.query_one("#picker-option-label", Static).update(label)
        self.set_class(highlighted, "picker-option-selected")


