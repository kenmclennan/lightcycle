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
        yield Static(id="status-hold")
        yield Static(id="status-version")
        yield Static(id="status-upgrade")

    def report(
        self,
        *,
        pool_running,
        pool_transition_kind=None,
        pool_transition_expired=False,
        breaker_is_open,
        breaker_is_probing,
        breaker_reset_at,
        version,
        upgrade_version,
        upgrade_error=None,
        hold=None,
    ):
        if pool_transition_kind == "start":
            glyph_key = "pool-start-timed-out" if pool_transition_expired else "pool-starting"
            label = "pool start timed out" if pool_transition_expired else "pool starting"
        elif pool_transition_kind == "stop":
            glyph_key = "pool-stop-timed-out" if pool_transition_expired else "pool-stopping"
            label = "pool stop timed out" if pool_transition_expired else "pool stopping"
        else:
            glyph_key = "pool-running" if pool_running else "pool-stopped"
            label = "pool running" if pool_running else "pool not running"
        pool_glyph, pool_colour = FOOTER_GLYPHS[glyph_key]
        pool = Text("%s %s" % (pool_glyph, label), style=COLOURS[pool_colour])
        pool.append(" (p)", style=COLOURS["dim"])
        self.query_one("#status-pool", Static).update(pool)

        if breaker_is_open and breaker_is_probing:
            since_ts = time.strftime("%H:%M:%S", time.localtime(breaker_reset_at))
            claude_glyph, claude_colour = FOOTER_GLYPHS["claude-probing"]
            claude_text = "%s claude probing · since %s" % (claude_glyph, since_ts)
        elif breaker_is_open:
            resume_ts = time.strftime("%H:%M:%S", time.localtime(breaker_reset_at))
            claude_glyph, claude_colour = FOOTER_GLYPHS["claude-unavailable"]
            claude_text = "%s claude unavailable · resumes %s" % (claude_glyph, resume_ts)
        else:
            claude_glyph, claude_colour = FOOTER_GLYPHS["claude-available"]
            claude_text = "%s claude available" % claude_glyph
        self.query_one("#status-claude", Static).update(Text(claude_text, style=COLOURS[claude_colour]))

        hold_widget = self.query_one("#status-hold", Static)
        if hold is not None and hold.holding:
            hold_glyph, hold_colour = FOOTER_GLYPHS["pool-holding"]
            text = "%s holding · %d/%d · %s" % (hold_glyph, hold.alive, hold.max_agents, hold.reason)
            if hold.system_pressure is not None:
                text += " (machine %d%%)" % round(hold.system_pressure * 100)
            hold_widget.update(Text(text, style=COLOURS[hold_colour]))
            hold_widget.display = True
        else:
            hold_widget.update("")
            hold_widget.display = False

        self.query_one("#status-version", Static).update(Text("v%s" % version, style=COLOURS["dim"]))

        upgrade_widget = self.query_one("#status-upgrade", Static)
        if upgrade_version is not None:
            upgrade_glyph, upgrade_colour = FOOTER_GLYPHS["upgrade-available"]
            upgrade_widget.update(
                Text("%s v%s available" % (upgrade_glyph, upgrade_version), style=COLOURS[upgrade_colour])
            )
            upgrade_widget.display = True
        elif upgrade_error is not None:
            upgrade_widget.update(
                Text("upgrade check failed: %s" % upgrade_error, style=COLOURS["dim"])
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
