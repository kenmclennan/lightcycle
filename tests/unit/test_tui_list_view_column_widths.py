import unittest

from lightcycle.adapters.tui.app import BacklogTable, BacklogView, DoneTable, DoneView
from lightcycle.adapters.tui.backlog_list import BacklogRow
from lightcycle.adapters.tui.done_list import DoneRow
from lightcycle.adapters.tui.row_grid import atomic_column_width
from tests.support.fake_store import FakeStore
from tests.support.tui_harness import launch, make_test_container

_SHORT = ("LC-1", "p")
_LONG = ("LC-1325", "lightcycle-workflows")


def _backlog_rows(*pairs):
    return [BacklogRow(id=i, project=p, repo="", title="title") for i, p in pairs]


def _done_rows(*pairs):
    return [
        DoneRow(id=i, project=p, repo="", title="title", cost="$1.25", time="3m")
        for i, p in pairs
    ]


class _ViewColumnWidths:
    press_count = 1

    def _launch(self):
        store = FakeStore()
        item = store.create_item("seed", "a description")
        store.complete_node(item, "done")
        session = launch(make_test_container(store=store), size=(160, 40))
        self.addCleanup(session.close)
        for _ in range(self.press_count):
            session.press("]")
        return session

    def _apply(self, session, rows):
        view = session.app.query_one(self.view_cls)
        session.run(lambda: self._call_apply(view, rows))
        session.pause()

    def _widths(self, session):
        table = session.app.query_one(self.table_cls)
        return {key: table.columns[key].width for key in ("id", "project")}

    def test_first_apply_rows_sizes_id_and_project_to_their_longest_value(self):
        session = self._launch()

        self._apply(session, self.rows(_LONG, ("LC-12", "lightcycle")))

        self.assertEqual(
            self._widths(session),
            {
                "id": atomic_column_width(["LC-1325", "LC-12"]),
                "project": atomic_column_width(["lightcycle-workflows", "lightcycle"]),
            },
        )

    def test_apply_rows_with_longer_values_resizes_the_columns_to_the_new_rows(self):
        session = self._launch()
        self._apply(session, self.rows(_SHORT))

        self._apply(session, self.rows(_LONG, _SHORT))

        self.assertEqual(
            self._widths(session),
            {
                "id": atomic_column_width(["LC-1325", "LC-1"]),
                "project": atomic_column_width(["lightcycle-workflows", "p"]),
            },
        )


class TestBacklogViewColumnWidths(_ViewColumnWidths, unittest.TestCase):
    view_cls = BacklogView
    table_cls = BacklogTable
    rows = staticmethod(_backlog_rows)

    def _call_apply(self, view, rows):
        view.apply_rows(rows, len(rows), None, None)


class TestDoneViewColumnWidths(_ViewColumnWidths, unittest.TestCase):
    press_count = 2
    view_cls = DoneView
    table_cls = DoneTable
    rows = staticmethod(_done_rows)

    def _call_apply(self, view, rows):
        view.apply_rows(rows, len(rows), None, None, None)


if __name__ == "__main__":
    unittest.main()
