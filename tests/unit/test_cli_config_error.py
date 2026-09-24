import io
import unittest
from contextlib import redirect_stderr
from unittest import mock

from lightcycle import cli
from lightcycle.config import ConfigError
from tests.support.fake_store import FakeStore


class _Cfg:
    def reconcile_config(self):
        pass

    def is_worker(self):
        return False


class _Container:
    def __init__(self):
        self.config = _Cfg()
        self.store = FakeStore()


class TestMainRendersConfigErrorAsOneLine(unittest.TestCase):
    def setUp(self):
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))

    def _run(self, argv, raising):
        err = io.StringIO()
        with mock.patch.object(cli, "Container", _Container):
            with mock.patch.object(cli, "cmd_status", raising):
                with redirect_stderr(err):
                    rc = cli.main(argv)
        return rc, err.getvalue()

    def test_config_error_exits_one_with_only_its_message(self):
        msg = "required config value 'workflow-retention' is not set. Add `workflow-retention: <value>` to /h/config (or run `lc init`)."

        def raising(_argv):
            raise ConfigError(msg)

        rc, err = self._run(["status"], raising)

        self.assertEqual(rc, 1)
        self.assertEqual(err, msg + "\n")

    def test_config_value_error_subclass_is_rendered_the_same_way(self):
        from lightcycle.config import ConfigValueError

        def raising(_argv):
            raise ConfigValueError("bad value")

        rc, err = self._run(["status"], raising)

        self.assertEqual(rc, 1)
        self.assertEqual(err, "bad value\n")


if __name__ == "__main__":
    unittest.main()
