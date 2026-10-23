import base64
import unittest

from lightcycle.adapters.tui.kitty_health_icon import KittyHealthIconAdapter, TuiTerminalWriter


class TestKittyHealthIconAdapter(unittest.TestCase):
    def setUp(self):
        self.out = []
        self.adapter = KittyHealthIconAdapter(self.out.append)

    def test_first_transmit_is_quiet_virtual_png_with_a_cell_box(self):
        self.adapter.transmit(7, b"png-bytes", 3)
        self.assertEqual(len(self.out), 1)
        escape = self.out[0]
        for part in ("f=100", "U=1", "q=2", "c=3", "r=2", "i=7", "a=T"):
            self.assertIn(part, escape)
        self.assertTrue(escape.startswith("\x1b_G") and escape.endswith("\x1b\\"))
        self.assertIn(base64.standard_b64encode(b"png-bytes").decode(), escape)

    def test_large_payload_is_chunked_with_q2_on_every_chunk(self):
        self.adapter.transmit(7, b"x" * 9000, 3)
        self.assertGreater(len(self.out), 1)
        for escape in self.out:
            self.assertIn("q=2", escape)
        self.assertIn("m=1", self.out[0])
        self.assertTrue(all("m=1" in e for e in self.out[:-1]))
        self.assertIn("m=0", self.out[-1])
        joined = "".join(e.split(";", 1)[1][:-2] for e in self.out)
        self.assertEqual(base64.standard_b64decode(joined), b"x" * 9000)

    def test_second_transmit_of_an_id_writes_nothing(self):
        self.adapter.transmit(7, b"a", 3)
        before = len(self.out)
        self.adapter.transmit(7, b"a", 3)
        self.assertEqual(len(self.out), before)

    def test_delete_all_deletes_each_id_quietly_then_forgets(self):
        self.adapter.transmit(7, b"a", 3)
        self.adapter.transmit(8, b"b", 3)
        self.out.clear()
        self.adapter.delete_all()
        self.assertEqual(len(self.out), 2)
        for escape in self.out:
            self.assertIn("a=d", escape)
            self.assertIn("q=2", escape)
        self.out.clear()
        self.adapter.delete_all()
        self.assertEqual(self.out, [])


class TestTuiTerminalWriter(unittest.TestCase):
    def test_unbound_is_a_no_op(self):
        TuiTerminalWriter()("data")

    def test_bound_forwards(self):
        got = []
        writer = TuiTerminalWriter()
        writer.bind(got.append)
        writer("data")
        self.assertEqual(got, ["data"])
