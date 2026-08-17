import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from lightcycle.adapters.tui.design_system import COLOURS, FOOTER_GLYPHS, GLOBAL_SHORTCUTS


class StatusBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(id="status-pool")
        yield Static(id="status-claude")
        yield Static(id="status-version")
        yield Static(id="status-upgrade")

    def report(self, *, pool_running, breaker_is_open, breaker_reset_at, version, upgrade_version):
        pool_glyph, pool_colour = FOOTER_GLYPHS["pool-running" if pool_running else "pool-stopped"]
        pool_text = "%s %s" % (pool_glyph, "pool running" if pool_running else "pool not running")
        self.query_one("#status-pool", Static).update(Text(pool_text, style=COLOURS[pool_colour]))

        if breaker_is_open:
            resume_ts = time.strftime("%H:%M:%S", time.localtime(breaker_reset_at))
            claude_glyph, claude_colour = FOOTER_GLYPHS["claude-unavailable"]
            claude_text = "%s claude unavailable · resumes %s" % (claude_glyph, resume_ts)
        else:
            claude_glyph, claude_colour = FOOTER_GLYPHS["claude-available"]
            claude_text = "%s claude available" % claude_glyph
        self.query_one("#status-claude", Static).update(Text(claude_text, style=COLOURS[claude_colour]))

        self.query_one("#status-version", Static).update(Text("v%s" % version, style=COLOURS["dim"]))

        upgrade_widget = self.query_one("#status-upgrade", Static)
        if upgrade_version is not None:
            upgrade_glyph, upgrade_colour = FOOTER_GLYPHS["upgrade-available"]
            upgrade_widget.update(
                Text("%s v%s available" % (upgrade_glyph, upgrade_version), style=COLOURS[upgrade_colour])
            )
            upgrade_widget.display = True
        else:
            upgrade_widget.update("")
            upgrade_widget.display = False


class ShortcutBar(Horizontal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shortcuts = ()

    def set_shortcuts(self, shortcuts):
        self._shortcuts = tuple(shortcuts)
        for child in list(self.children):
            child.remove()
        for key, action in self._shortcuts:
            self.mount(Static(key, classes="shortcut-key", markup=False))
            self.mount(Static(action, classes="shortcut-action", markup=False))

    @property
    def shortcuts(self):
        return self._shortcuts


class DashboardFooter(Vertical):
    def __init__(self, *args, shortcuts=GLOBAL_SHORTCUTS, **kwargs):
        super().__init__(*args, **kwargs)
        self._shortcuts = shortcuts

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        yield ShortcutBar(id="shortcut-bar")

    def on_mount(self) -> None:
        self.query_one(ShortcutBar).set_shortcuts(self._shortcuts)
