import unittest

from lightcycle.cli_commands import COMMANDS, build_parser
from lightcycle.domain.work import cap_rules_help


class TestCapHelpText(unittest.TestCase):
    def test_done_and_set_help_list_the_limits(self):
        for verb in ("done", "set"):
            text = build_parser(COMMANDS[verb]).format_help()
            self.assertIn("".join(cap_rules_help().split()), "".join(text.split()))
