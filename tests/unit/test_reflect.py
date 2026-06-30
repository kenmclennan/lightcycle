import unittest

from the_grid.domain.reflect import build_reflection, spec_hash_from_bytes
from the_grid.domain.reflection import Reflection


class TestReflectionVO(unittest.TestCase):
    def test_from_dict_as_dict_round_trip(self):
        d = {"task": "t-1", "feedback": "fb", "spec_hash": "aabbccdd"}
        self.assertEqual(Reflection.from_dict(d).as_dict(), d)

    def test_from_dict_tolerates_missing_fields(self):
        r = Reflection.from_dict({"task": "t-1"})
        self.assertEqual(r.feedback, "")
        self.assertEqual(r.spec_hash, "unknown")


class TestSpecHashFromBytes(unittest.TestCase):
    def test_returns_8_hex_chars(self):
        h = spec_hash_from_bytes(b"# spec\ncontent")
        self.assertEqual(len(h), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_deterministic(self):
        data = b"hello world"
        self.assertEqual(spec_hash_from_bytes(data), spec_hash_from_bytes(data))

    def test_different_for_different_input(self):
        self.assertNotEqual(spec_hash_from_bytes(b"a"), spec_hash_from_bytes(b"b"))


class TestBuildReflection(unittest.TestCase):
    def test_carries_feedback(self):
        r = build_reflection("task-1", feedback="pytest not found; used bash tests/run.sh",
                             spec_hash="abc12345")
        self.assertEqual(r.task, "task-1")
        self.assertEqual(r.feedback, "pytest not found; used bash tests/run.sh")
        self.assertEqual(r.spec_hash, "abc12345")

    def test_defaults(self):
        r = build_reflection("task-1")
        self.assertEqual(r.feedback, "")
        self.assertEqual(r.spec_hash, "unknown")

    def test_json_shape_stable(self):
        r = build_reflection("t", feedback="x", spec_hash="aabbccdd")
        self.assertEqual(set(r.as_dict()), {"task", "feedback", "spec_hash"})


if __name__ == "__main__":
    unittest.main()
