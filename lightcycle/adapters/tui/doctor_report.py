import time

from lightcycle.adapters.tui.artifact_viewer import ArtifactTextBody
from lightcycle.adapters.tui.design_system import COLOURS, DOCTOR_REPORT_SHORTCUTS
from lightcycle.adapters.tui.footer import DashboardFooter
from lightcycle.domain.health import problem_lines
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static


class DoctorReportScreen(Screen, inherit_bindings=False):
    BINDINGS = [b for b in Screen.BINDINGS if b.key != "tab"] + [
        Binding("escape", "close", "Back", show=False),
        Binding("tab", "close", "Back", show=False),
        Binding("left", "close", "Back", show=False),
    ]

    CSS = f"""
    #doctor-report-header {{
        height: 2;
        border-bottom: solid {COLOURS["border"]};
    }}
    ArtifactTextBody {{
        height: 1fr;
    }}
    """

    def __init__(self, report, summary, checked_at):
        super().__init__()
        self._report = report
        self._summary = summary
        self._checked_at = checked_at

    def compose(self) -> ComposeResult:
        yield Static(id="doctor-report-header")
        yield ArtifactTextBody(id="doctor-report-body", highlight=False, markup=False, wrap=True)
        yield DashboardFooter(id="doctor-report-footer", shortcuts=DOCTOR_REPORT_SHORTCUTS)

    def on_mount(self) -> None:
        self.app._refresh_status_bar()
        header = Text()
        header.append("doctor", style=COLOURS["cyan"])
        if self._summary:
            header.append(" · %s" % self._summary, style=COLOURS["dim"])
        header.append(
            " · checked %s" % time.strftime("%H:%M", time.localtime(self._checked_at)),
            style=COLOURS["dim"],
        )
        self.query_one("#doctor-report-header", Static).update(header)
        body = self.query_one(ArtifactTextBody)
        for category, problems in self._report.problems.items():
            if not problems:
                continue
            body.write(Text("%s:" % category, style=COLOURS["cyan"]))
            for line in problem_lines(problems):
                body.write(Text(line))
        self.set_focus(body)

    def action_close(self) -> None:
        self.app.pop_screen()
