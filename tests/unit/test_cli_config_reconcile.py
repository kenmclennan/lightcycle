import unittest
from unittest import mock

from lightcycle import cli


class _Cfg:
    def __init__(self):
        self.reconciled = 0

    def reconcile_config(self):
        self.reconciled += 1

    def is_worker(self):
        return False


class _Container:
    def __init__(self):
        self.config = _Cfg()


class TestMainReconcilesConfig(unittest.TestCase):
    def setUp(self):
        self._orig = cli._container
        self.addCleanup(lambda: cli.set_container(self._orig))

    def test_main_reconciles_config_after_building_container(self):
        fake = _Container()
        with mock.patch.object(cli, "Container", lambda: fake), \
                mock.patch.object(cli, "cmd_status", lambda argv: 0):
            rc = cli.main(["status"])
        self.assertEqual(rc, 0)
        self.assertEqual(fake.config.reconciled, 1)

    def test_version_and_upgrade_do_not_build_container(self):
        with mock.patch.object(cli, "Container", lambda: self.fail("built container")):
            cli.main(["version"])
