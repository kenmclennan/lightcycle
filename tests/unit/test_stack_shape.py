import unittest
from dataclasses import replace

from lightcycle.domain.pool import stack_shape
from tests.support.stacked import TRUNK, build_stack, layer_url, rederive, with_state


def _baseline(count=3):
    layers = build_stack(count)
    bases = {layer_url(l.number): l.base_ref for l in layers}
    return stack_shape.record_of(layers, bases, None)


def _stale(layers, number):
    return tuple(replace(l, base_ref="layer-%d" % (number - 1)) if l.number == number else l
                 for l in layers)


def _compare(previous, layers, bases):
    current = [{"base": bases.get(l.number)} for l in layers]
    return stack_shape.compare(previous, layers, current, False)


class TestCompareTrunk(unittest.TestCase):
    def test_the_bottom_layer_retargeted_onto_another_base_is_a_shape_change(self):
        layers = rederive(build_stack(3))
        layers = tuple(replace(l, base_ref="release/1") if l.number == 1 else l for l in layers)

        diff = _compare(_baseline(), layers, {1: "release/1", 2: "layer-1", 3: "layer-2"})

        self.assertEqual(len(diff.differences), 1)
        self.assertIn("layer 1 of 3", diff.differences[0])
        self.assertIn("retargeted onto release/1", diff.differences[0])
        self.assertIn("main", diff.differences[0])

    def test_the_bottom_layer_observed_on_the_recorded_trunk_is_not_a_shape_change(self):
        diff = _compare(_baseline(), build_stack(3), {1: TRUNK, 2: "layer-1", 3: "layer-2"})

        self.assertEqual(diff.differences, [])

    def test_a_layer_on_the_trunk_after_the_bottom_merges_is_not_a_shape_change(self):
        layers = _stale(rederive(with_state(build_stack(3), 1, "merged")), 2)

        diff = _compare(_baseline(), layers, {2: TRUNK, 3: "layer-2"})

        self.assertEqual(diff.differences, [])

    def test_a_layer_on_the_trunk_while_the_bottom_is_open_is_a_shape_change(self):
        layers = _stale(build_stack(3), 2)

        diff = _compare(_baseline(), layers, {1: TRUNK, 2: TRUNK, 3: "layer-2"})

        self.assertEqual(len(diff.differences), 1)
        self.assertIn("layer 2 of 3", diff.differences[0])
        self.assertIn("retargeted onto main", diff.differences[0])

    def test_a_layer_on_the_trunk_with_a_middle_layer_open_is_a_shape_change(self):
        layers = rederive(with_state(build_stack(3), 1, "merged"))

        diff = _compare(_baseline(), layers, {2: "layer-1", 3: TRUNK})

        self.assertEqual(len(diff.differences), 1)
        self.assertIn("layer 3 of 3", diff.differences[0])

    def test_the_layer_just_above_the_last_merged_one_sits_exactly_on_the_boundary(self):
        layers = rederive(with_state(with_state(build_stack(3), 1, "merged"), 2, "merged"))
        layers = tuple(replace(l, base_ref="layer-2") if l.number == 3 else l for l in layers)

        diff = _compare(_baseline(), layers, {3: TRUNK})

        self.assertEqual(diff.differences, [])

    def test_a_retarget_onto_another_branch_after_a_merge_is_a_shape_change(self):
        layers = _stale(rederive(with_state(build_stack(3), 1, "merged")), 2)

        diff = _compare(_baseline(), layers, {2: "feature-x", 3: "layer-2"})

        self.assertEqual(len(diff.differences), 1)
        self.assertIn("retargeted onto feature-x", diff.differences[0])

    def test_a_legacy_record_with_no_trunk_keeps_the_old_behaviour(self):
        previous = _baseline()
        previous[0]["base"] = None
        previous[0]["state"] = "merged"
        layers = _stale(rederive(with_state(build_stack(3), 1, "merged")), 2)

        diff = _compare(previous, layers, {2: TRUNK, 3: "layer-2"})

        self.assertEqual(len(diff.differences), 1)

    def test_record_of_keeps_a_merged_layers_base(self):
        layers = rederive(with_state(build_stack(3), 1, "merged"))

        record = stack_shape.record_of(layers, {}, _baseline())

        self.assertEqual(record[0]["number"], 1)
        self.assertEqual(record[0]["base"], TRUNK)


class TestMergeBlocker(unittest.TestCase):
    def test_merge_blocker_names_the_first_unmerged_layer_or_a_foreign_top(self):
        top = layer_url(3)
        cases = [
            (build_stack(3, states={1: "merged", 2: "merged", 3: "merged"}), top, None),
            (
                build_stack(3, states={3: "merged"}), top,
                "layer 1 of 3 (%s) is open" % layer_url(1),
            ),
            (
                build_stack(3, states={1: "merged", 2: "merged", 3: "closed"}), top,
                "layer 3 of 3 (%s) is closed" % layer_url(3),
            ),
            (
                build_stack(3, states={1: "merged", 2: "merged", 3: "merged"}), layer_url(2),
                "the stack's top layer is %s, not this run's PR %s" % (top, layer_url(2)),
            ),
        ]
        for layers, pr, expected in cases:
            self.assertEqual(stack_shape.merge_blocker(layers, pr), expected)

    def test_abandoned_is_true_only_for_merged_or_closed_layers_with_the_run_pr_closed_on_top(self):
        top = layer_url(3)
        cases = [
            (build_stack(3, states={1: "closed", 2: "closed", 3: "closed"}), True),
            (build_stack(3, states={1: "merged", 2: "closed", 3: "closed"}), True),
            (build_stack(3, states={1: "closed", 2: "open", 3: "closed"}), False),
            (build_stack(3, states={1: "closed", 2: "merged", 3: "merged"}), False),
            (build_stack(3, states={1: "merged", 2: "merged", 3: "closed"}), True),
            (build_stack(3, states={1: "merged", 2: "merged", 3: "merged"}), False),
        ]
        for layers, expected in cases:
            self.assertEqual(stack_shape.abandoned(layers, top), expected, [l.state for l in layers])
        self.assertFalse(stack_shape.abandoned((), top))
        closed = build_stack(3, states={1: "closed", 2: "closed", 3: "closed"})
        self.assertFalse(stack_shape.abandoned(closed, layer_url(2)))


class TestStackShapeHelpers(unittest.TestCase):
    def test_out_of_order_merges_names_each_merged_layer_above_an_open_one(self):
        self.assertEqual(stack_shape.out_of_order_merges(build_stack(3)), [])
        cascade = with_state(build_stack(3), 1, "merged")
        self.assertEqual(stack_shape.out_of_order_merges(cascade), [])
        above = with_state(build_stack(3), 3, "merged")
        self.assertEqual(
            stack_shape.out_of_order_merges(above),
            ["layer 3 of 3 (%s) merged while a layer below it is still open" % layer_url(3)])
        two = with_state(with_state(build_stack(3), 2, "merged"), 3, "merged")
        found = stack_shape.out_of_order_merges(two)
        self.assertEqual(len(found), 2)
        self.assertIn("layer 2 of 3", found[0])
        self.assertIn("layer 3 of 3", found[1])

    def test_closed_layer_labels_names_each_closed_layer(self):
        layers = with_state(with_state(build_stack(3), 1, "closed"), 3, "closed")
        self.assertEqual(
            stack_shape.closed_layer_labels(layers),
            ["layer 1 of 3 (%s)" % layer_url(1), "layer 3 of 3 (%s)" % layer_url(3)])
        self.assertEqual(stack_shape.closed_layer_labels(build_stack(3)), [])
