import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.link_artifact import LinkArtifactInput, LinkArtifactUseCase
from tests.support.fake_store import FakeStore


class TestGuidanceCited(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.item = self.store.create_item("t", "d")
        self.step = self.store.create_step(step="build", role="agent", parent=self.item)
        self.store.replace_artifact(self.step, "guidance-delivered", "a/x\nb\nc", internal=True)
        self.use = LinkArtifactUseCase(self.store)

    def _attach(self, value, target=None, **kw):
        self.use.execute(LinkArtifactInput(
            item=target or self.step, atype="guidance-cited", value=value, **kw))

    def _cited(self):
        return [a for a in self.store.item_artifacts(self.step) if a.type == "guidance-cited"]

    def _refused(self, value, target=None, **kw):
        with self.assertRaises(UseCaseError) as cm:
            self._attach(value, target, **kw)
        return str(cm.exception)

    def test_success_stores_newline_joined_internal_and_keeps_label(self):
        self._attach("a/x, b", label="mine")
        (rec,) = self._cited()
        self.assertEqual((rec.value, rec.internal, rec.label), ("a/x\nb", True, "mine"))

    def test_every_delivered_id_is_accepted(self):
        self._attach("a/x, b, c")
        self.assertEqual(self._cited()[0].value, "a/x\nb\nc")

    def test_one_of_several_delivered_is_accepted(self):
        self._attach("c")
        self.assertEqual(self._cited()[0].value, "c")

    def test_an_item_is_refused_as_not_a_step(self):
        self.assertEqual(
            self._refused("a/x", self.item),
            "'%s' is not a step - guidance-cited attaches to the step that was delivered the guidance"
            % self.item,
        )

    def test_unknown_id_is_refused_as_not_a_step(self):
        self.assertIn("is not a step", self._refused("a/x", "NOPE-9"))

    def test_step_without_delivery_is_refused(self):
        other = self.store.create_step(step="build", role="agent", parent=self.item)
        self.assertEqual(
            self._refused("a/x", other),
            "step '%s' was delivered no guidance entries, so there is nothing to cite - "
            "do not attach guidance-cited" % other,
        )

    def test_empty_delivery_is_refused(self):
        self.store.replace_artifact(self.step, "guidance-delivered", "", internal=True)
        self.assertIn("nothing to cite", self._refused("a/x"))

    def test_no_ids_is_refused(self):
        self.assertEqual(
            self._refused(","),
            "guidance-cited on '%s' names no entry id - pass the delivered ids as a "
            "comma-separated list" % self.step,
        )

    def test_undelivered_id_is_refused_naming_it_and_the_delivered(self):
        self.assertEqual(
            self._refused("zzz"),
            "guidance-cited on '%s' names zzz which were not delivered to that step - "
            "delivered: a/x, b, c; cite only entries from the guidance section in your prompt"
            % self.step,
        )
        self.assertEqual(self._cited(), [])

    def test_mixed_list_names_only_the_undelivered_and_stores_nothing(self):
        msg = self._refused("a/x, y, z")
        self.assertIn("names y, z which", msg)
        self.assertEqual(self._cited(), [])

    def test_second_citation_is_refused_even_with_replace_and_label(self):
        self._attach("a/x")
        msg = self._refused("b", replace=True, label="other")
        self.assertEqual(
            msg,
            "step '%s' already has a guidance-cited record (a/x) - cite once; "
            "the first record stands" % self.step,
        )
        self.assertEqual(len(self._cited()), 1)

    def test_second_attach_with_a_bad_id_reports_the_bad_id(self):
        self._attach("a/x")
        self.assertIn("were not delivered", self._refused("zzz"))
