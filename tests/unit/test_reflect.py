import unittest

from lightcycle.domain.feedback import Reflection


class TestReflectionVO(unittest.TestCase):
    def test_from_dict_as_dict_round_trip(self):
        d = {"task": "t-1", "feedback": "fb", "spec_hash": "aabbccdd"}
        self.assertEqual(Reflection.from_dict(d).as_dict(), d)

    def test_from_dict_tolerates_missing_fields(self):
        r = Reflection.from_dict({"task": "t-1"})
        self.assertEqual(r.feedback, "")
        self.assertEqual(r.spec_hash, "unknown")


class TestSpecHashOf(unittest.TestCase):
    def test_returns_8_hex_chars(self):
        h = Reflection.spec_hash_of(b"# spec\ncontent")
        self.assertEqual(len(h), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_deterministic(self):
        data = b"hello world"
        self.assertEqual(Reflection.spec_hash_of(data), Reflection.spec_hash_of(data))

    def test_different_for_different_input(self):
        self.assertNotEqual(Reflection.spec_hash_of(b"a"), Reflection.spec_hash_of(b"b"))


class TestCreate(unittest.TestCase):
    def test_carries_feedback(self):
        r = Reflection.create(
            "task-1", feedback="pytest not found; used bash tests/run.sh", spec_hash="abc12345"
        )
        self.assertEqual(r.task, "task-1")
        self.assertEqual(r.feedback, "pytest not found; used bash tests/run.sh")
        self.assertEqual(r.spec_hash, "abc12345")

    def test_defaults(self):
        r = Reflection.create("task-1")
        self.assertEqual(r.feedback, "")
        self.assertEqual(r.spec_hash, "unknown")

    def test_json_shape_stable(self):
        r = Reflection.create("t", feedback="x", spec_hash="aabbccdd")
        self.assertEqual(set(r.as_dict()), {"task", "feedback", "spec_hash"})


if __name__ == "__main__":
    unittest.main()
