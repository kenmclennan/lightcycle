import unittest

from lightcycle.application.work import SearchInput, SearchUseCase
from lightcycle.application.work.watched_steps import watched_step_ids
from tests.support.query_counter import QueryCounter
from tests.support.sqlite_store_factory import make_sqlite_store


def _search_query_count(unrelated_count):
    s = make_sqlite_store()
    matched = s.create_item("a needle to find", "a description")
    for i in range(unrelated_count):
        item = s.create_item("unrelated %d" % i, "a description")
        s.create_step("unrelated step %d" % i, parent=item)
    counter = QueryCounter(s._conn)
    resp = SearchUseCase(s).execute(SearchInput(text="needle"))
    assert [m.node.id for m in resp.matches] == [matched]
    return counter.count


def _item_rollup_query_count(done_child_count):
    s = make_sqlite_store()
    item = s.create_item("item", "a description")
    for i in range(done_child_count):
        step = s.create_step("step %d" % i, parent=item)
        s.close(step, "done")
    counter = QueryCounter(s._conn)
    s.get_node(item)
    return counter.count


class TestSearchQueryCount(unittest.TestCase):
    def test_query_count_does_not_grow_with_unmatched_population(self):
        small = _search_query_count(5)
        large = _search_query_count(200)
        self.assertEqual(small, large)


class TestWatchedStepIdsQueryCount(unittest.TestCase):
    def test_issues_no_more_queries_than_a_full_node_scan(self):
        s = make_sqlite_store()
        for i in range(20):
            step = s.create_step("step %d" % i, role="human")
            s.set_watched_step(step, "some-other-id")

        counter = QueryCounter(s._conn)
        s.all_nodes()
        baseline = counter.count

        counter.reset()
        watched_step_ids(s)

        self.assertLessEqual(counter.count, baseline)


class TestRollupQueryCount(unittest.TestCase):
    def test_get_node_query_count_does_not_grow_with_done_child_count(self):
        small = _item_rollup_query_count(3)
        large = _item_rollup_query_count(200)
        self.assertEqual(small, large)

    def test_all_nodes_query_count_does_not_grow_with_done_child_count(self):
        def run(done_child_count):
            s = make_sqlite_store()
            item = s.create_item("item", "a description")
            for i in range(done_child_count):
                step = s.create_step("step %d" % i, parent=item)
                s.close(step, "done")
            counter = QueryCounter(s._conn)
            s.all_nodes()
            return counter.count

        small = run(3)
        large = run(200)
        self.assertEqual(small, large)


if __name__ == "__main__":
    unittest.main()
