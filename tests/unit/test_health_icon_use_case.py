import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.pool import HealthIconUseCase
from lightcycle.config import Config
from lightcycle.domain.pool import HEALTH_IMAGE_IDS, HEALTH_IMAGE_STATES, TickHealth
from tests.support.fake_fs import FakeFs
from tests.support.fake_health_icon import FakeHealthIcon
from tests.support.png_bytes import png_bytes


def _config(on="on", **extra):
    home = tempfile.mkdtemp()
    values = {
        "tui-health-icons": on, "tui-health-icon-dir": "icons",
        "tui-health-icon-0": "h0.png", "tui-health-icon-1": "h1.png",
        "tui-health-icon-2": "h2.png", "tui-health-icon-3": "h3.png",
        "tui-health-icon-4": "h4.png", "tui-health-icon-busy": "hb.png",
    }
    values.update(extra)
    path = os.path.join(home, "config")
    Path(path).write_text("".join("%s: %s\n" % kv for kv in values.items()))
    return Config(environ={"LC_HOME": home, "LC_CONFIG": path})


class _Github:
    known = True

    def __init__(self, remaining, limit=100):
        self.remaining = remaining
        self.limit = limit


HEALTHY = TickHealth("healthy", 1, 1)
STALLED = TickHealth("stalled", None, 500)
BASE = dict(
    pool_state="running", tick_health=HEALTHY, poll_seconds=5, breaker_is_open=False,
    github=None, upgrade_available=False, config_changed=False, busy=False,
)


def _files(config, states=HEALTH_IMAGE_STATES, data=None):
    return {
        config.tui_health_icon_path(s): data if data is not None else png_bytes() for s in states
    }


def _use_case(config, files):
    fs = FakeFs(files=files)
    icon = FakeHealthIcon()
    return HealthIconUseCase(fs, config, icon), icon, fs


class TestHealthIconUseCase(unittest.TestCase):
    def test_feature_off_returns_none_and_touches_no_file(self):
        config = _config(on="off")
        use_case, icon, fs = _use_case(config, _files(config))
        self.assertIsNone(use_case.reading(**BASE))
        self.assertEqual(icon.transmitted, [])

    def test_each_score_selects_its_state_image(self):
        cases = {
            "0": {},
            "1": dict(upgrade_available=True),
            "2": dict(github=_Github(50)),
            "3": dict(github=_Github(30)),
            "4": dict(breaker_is_open=True),
            "busy": dict(busy=True),
        }
        for state, change in cases.items():
            config = _config()
            use_case, icon, _ = _use_case(config, _files(config))
            reading = use_case.reading(**{**BASE, **change})
            self.assertEqual(reading.state, state)
            self.assertEqual(reading.image_id, HEALTH_IMAGE_IDS[state])
            self.assertEqual(icon.transmitted[0][0], HEALTH_IMAGE_IDS[state])
            self.assertEqual(reading.columns, 3)

    def test_busy_does_not_override_a_nonzero_score(self):
        config = _config()
        use_case, _, _ = _use_case(config, _files(config))
        self.assertEqual(use_case.reading(**{**BASE, "busy": True, "tick_health": STALLED}).state, "4")

    def test_missing_file_returns_none_then_loads_once_present(self):
        config = _config()
        use_case, icon, fs = _use_case(config, {})
        self.assertIsNone(use_case.reading(**BASE))
        self.assertEqual(icon.transmitted, [])
        fs._files.update(_files(config, ["0"]))
        self.assertIsNotNone(use_case.reading(**BASE))
        self.assertEqual(len(icon.transmitted), 1)

    def test_unreadable_and_non_png_files_return_none(self):
        config = _config()
        path = config.tui_health_icon_path("0")
        use_case, icon, fs = _use_case(config, {path: b"not a png at all, just some text"})
        self.assertIsNone(use_case.reading(**BASE))

        def boom(p):
            raise OSError("denied")

        fs.read_bytes = boom
        fs._files[path] = png_bytes()
        self.assertIsNone(use_case.reading(**BASE))
        self.assertEqual(icon.transmitted, [])

    def test_repeat_poll_does_not_transmit_again(self):
        config = _config()
        use_case, icon, _ = _use_case(config, _files(config))
        use_case.reading(**BASE)
        use_case.reading(**BASE)
        self.assertEqual(len(icon.transmitted), 1)

    def test_two_states_transmit_two_ids(self):
        config = _config()
        use_case, icon, _ = _use_case(config, _files(config))
        use_case.reading(**BASE)
        use_case.reading(**{**BASE, "breaker_is_open": True})
        self.assertEqual([t[0] for t in icon.transmitted], [HEALTH_IMAGE_IDS["0"], HEALTH_IMAGE_IDS["4"]])

    def test_config_error_returns_none(self):
        config = _config(**{"tui-health-icon-dir": "../escape"})
        use_case, _, _ = _use_case(config, {})
        self.assertIsNone(use_case.reading(**BASE))

    def test_release_deletes_and_forgets(self):
        config = _config()
        use_case, icon, _ = _use_case(config, _files(config))
        use_case.reading(**BASE)
        use_case.release()
        self.assertEqual(icon.deleted, 1)
        use_case.reading(**BASE)
        self.assertEqual(len(icon.transmitted), 2)

    def test_only_present_states_get_readings(self):
        config = _config()
        present = ["0", "2", "busy"]
        use_case, icon, _ = _use_case(config, _files(config, present))
        polls = {
            "0": {}, "1": dict(upgrade_available=True), "2": dict(github=_Github(50)),
            "3": dict(github=_Github(30)), "4": dict(breaker_is_open=True), "busy": dict(busy=True),
        }
        got = {s: use_case.reading(**{**BASE, **c}) for s, c in polls.items()}
        for state in HEALTH_IMAGE_STATES:
            self.assertEqual(got[state] is not None, state in present, state)
        self.assertEqual(
            sorted(t[0] for t in icon.transmitted),
            sorted(HEALTH_IMAGE_IDS[s] for s in present))
