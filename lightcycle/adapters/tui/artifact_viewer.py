from lightcycle.adapters.tui.design_system import (
    COLOURS,
    LIST_ARTIFACT_SHORTCUTS,
    TEXT_ARTIFACT_SHORTCUTS,
)
from lightcycle.adapters.tui.footer import DashboardFooter
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    RichLog,
    Static,
)


class ArtifactTextBody(RichLog):
    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]


class ArtifactListTable(DataTable):
    _BASE = [b for b in DataTable.BINDINGS if b.key not in ("left", "right")]

    BINDINGS = _BASE + [
        Binding("ctrl+u", "page_up", "Page up", show=False),
        Binding("ctrl+d", "page_down", "Page down", show=False),
    ]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(*args, **kwargs)


class ArtifactViewerHeader(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(id="artifact-viewer-kind")
        yield Static(id="artifact-viewer-count")

    def update(self, artifact_type, node_id, count_text) -> None:
        kind_text = Text()
        kind_text.append(artifact_type, style=COLOURS["cyan"])
        kind_text.append(" · %s" % node_id, style=COLOURS["dim"])
        self.query_one("#artifact-viewer-kind", Static).update(kind_text)
        self.query_one("#artifact-viewer-count", Static).update(
            Text(count_text, style=COLOURS["dim"]) if count_text else ""
        )


class ArtifactViewerScreen(Screen, inherit_bindings=False):
    BINDINGS = [b for b in Screen.BINDINGS if b.key != "tab"] + [
        Binding("escape", "close", "Back", show=False),
        Binding("tab", "close", "Back", show=False),
        Binding("left", "close", "Back", show=False),
    ]

    CSS = f"""
    ArtifactViewerHeader {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    #artifact-viewer-kind {{
        width: auto;
    }}
    #artifact-viewer-count {{
        width: 1fr;
        content-align: right middle;
    }}
    """

    def __init__(self, artifact, node_id):
        super().__init__()
        self._artifact = artifact
        self._node_id = node_id

    def on_mount(self) -> None:
        self.app._refresh_status_bar()

    def action_close(self) -> None:
        self.app.pop_screen()


class TextArtifactViewerScreen(ArtifactViewerScreen):
    CSS = ArtifactViewerScreen.CSS + """
    ArtifactTextBody {
        height: 1fr;
    }
    """

    def __init__(self, artifact, node_id, position, total):
        super().__init__(artifact, node_id)
        self._position = position
        self._total = total

    def compose(self) -> ComposeResult:
        yield ArtifactViewerHeader(id="artifact-viewer-header")
        yield ArtifactTextBody(id="artifact-viewer-body", highlight=False, markup=False, wrap=True)
        yield DashboardFooter(id="artifact-viewer-footer", shortcuts=TEXT_ARTIFACT_SHORTCUTS)

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one(ArtifactViewerHeader).update(
            self._artifact.type, self._node_id, "%d / %d" % (self._position, self._total)
        )
        body = self.query_one(ArtifactTextBody)
        body.write(Text(self._artifact.value))
        self.set_focus(body)


class ListArtifactViewerScreen(ArtifactViewerScreen):
    CSS = ArtifactViewerScreen.CSS + """
    ArtifactListTable {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield ArtifactViewerHeader(id="artifact-viewer-header")
        yield ArtifactListTable(id="artifact-viewer-list")
        yield DashboardFooter(id="artifact-viewer-footer", shortcuts=LIST_ARTIFACT_SHORTCUTS)

    def on_mount(self) -> None:
        super().on_mount()
        table = self.query_one(ArtifactListTable)
        table.cursor_type = "row"
        table.show_header = False
        items = [line for line in self._artifact.value.splitlines() if line.strip()]
        self.query_one(ArtifactViewerHeader).update(
            self._artifact.type,
            self._node_id,
            "%d item%s" % (len(items), "" if len(items) == 1 else "s"),
        )
        table.add_column("value", key="value")
        for index, item in enumerate(items):
            table.add_row(item, key=str(index))
        if items:
            self.set_focus(table)
