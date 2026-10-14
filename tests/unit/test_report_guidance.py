import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import lightcycle.cli as cli_mod
from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect.report_guidance import ReportGuidanceUseCase, parse_since
from lightcycle.config import Config
from lightcycle.container import Container
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore

ROOT = "/kb"
ISSUE_A = "https://github.com/x/y/issues/1"
ISSUE_B = "https://github.com/x/y/issues/2"


def _cfg():
    path = os.path.join(tempfile.mkdtemp(), "config")
    Path(path).write_text(
        "guidance-unused-after-deliveries: 60\nguidance-dormant-days: 60\n")
    return Config(environ={"LC_CONFIG": path})


def _entry(status="stable", covers=None, stale_after=None, facets=None, steps=None):
    lines = ["---", "type: Guidance", "status: %s" % status, "verified: ken"]
    if covers:
        lines.append("covers: %s" % covers)
    if stale_after:
        lines.append("stale_after: %s" % stale_after)
    lines.append("applies-to:")
    if facets is not None:
        lines.append("  facets: [%s]" % ", ".join(facets))
    if steps is not None:
        lines.append("  steps: [%s]" % ", ".join(steps))
    lines += ["---", "", "body", ""]
    return "\n".join(lines).encode()


def _setup(files, github=None, added=None):
    if added is None:
        added = {name: "2020-01-01T00:00:00+00:00" for name in files}
    store = FakeStore()
    store.add_project("guidance", local_path=ROOT)
    fs = FakeFs(dirs={ROOT: []})
    git = FakeGit(ref="origin/main", ref_files={"origin/main": dict(files)}, added=added)
    github = github or FakeGitHub()
    return store, fs, github, ReportGuidanceUseCase(store, fs, git, github, _cfg())


def _step(store, item, delivered, cited=None, created_at=None, stage="write-code"):
    sid = store.create_step(step=stage, role="agent", parent=item)
    if delivered is not None:
        store.add_artifact(sid, "guidance-delivered", delivered, internal=True)
    if cited is not None:
        store.add_artifact(sid, "guidance-cited", cited, internal=True)
    if created_at:
        store._records[sid]["created_at"] = created_at
    return sid


def _rows(report):
    return {r.id: r for r in report.rows}


class TestCounts(unittest.TestCase):
    def test_no_readable_ref_adds_a_note_and_no_rows(self):
        store = FakeStore()
        store.add_project("guidance", local_path=ROOT)
        git = FakeGit(origin="git@x:kb.git", ref=None)
        report = ReportGuidanceUseCase(
            store, FakeFs(dirs={ROOT: []}), git, FakeGitHub(), _cfg()).execute(0.0)
        self.assertEqual(report.rows, ())
        self.assertEqual(len(report.notes), 1)
        self.assertIn("not been fetched", report.notes[0])

    def test_counts_and_last_delivered_match_the_records(self):
        store, fs, gh, use = _setup({"a.md": _entry(), "b.md": _entry()})
        i1, i2 = store.create_item("t", "d"), store.create_item("u", "d")
        _step(store, i1, "a\nb", cited="a", created_at="2026-10-01T09:00:00+00:00")
        _step(store, i1, "a\nghost", created_at="2026-10-05T09:00:00+00:00")
        _step(store, i2, "", created_at="2026-10-09T09:00:00+00:00")
        rows = _rows(use.execute(time.time()))
        self.assertEqual((rows["a"].deliveries, rows["a"].citations), (2, 1))
        self.assertEqual((rows["b"].deliveries, rows["b"].citations), (1, 0))
        self.assertEqual(rows["a"].last_delivered, "2026-10-05T09:00:00+00:00")
        self.assertNotIn("ghost", rows)

    def test_report_writes_nothing(self):
        store, fs, gh, use = _setup({"a.md": _entry(covers=ISSUE_A)}, FakeGitHub(
            issue_states={ISSUE_A: "CLOSED"}))
        item = store.create_item("t", "d")
        _step(store, item, "a")
        before = [list(store.item_artifacts(s.id)) for s in store.all_steps_including_done()]
        notes_before = [s.notes for s in store.all_steps_including_done()]
        use.execute(time.time())
        after = [list(store.item_artifacts(s.id)) for s in store.all_steps_including_done()]
        self.assertEqual(before, after)
        self.assertEqual(notes_before, [s.notes for s in store.all_steps_including_done()])
        self.assertEqual(fs.writes, [])

    def test_unregistered_or_missing_repo_raises(self):
        with self.assertRaises(UseCaseError):
            ReportGuidanceUseCase(FakeStore(), FakeFs(), FakeGit(), FakeGitHub(), _cfg()).execute(0.0)
        store = FakeStore()
        store.add_project("guidance", local_path="/gone")
        with self.assertRaises(UseCaseError):
            ReportGuidanceUseCase(store, FakeFs(), FakeGit(), FakeGitHub(), _cfg()).execute(0.0)


class TestNewEntries(unittest.TestCase):
    def test_recent_add_date_gives_a_note_and_an_old_one_flags(self):
        now = time.time()
        recent = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - 3 * 86400))
        old = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - 90 * 86400))
        store, fs, gh, use = _setup(
            {"new.md": _entry(), "old.md": _entry(), "unknown.md": _entry()},
            added={"new.md": recent, "old.md": old})
        rows = _rows(use.execute(now))
        self.assertEqual(rows["new"].flags, ())
        self.assertEqual(rows["new"].notes, ("new - 3 of 60 days old",))
        self.assertEqual([f.name for f in rows["old"].flags], ["never-delivered"])
        self.assertEqual([f.name for f in rows["unknown"].flags], ["never-delivered"])
        self.assertIn("add date unreadable", rows["unknown"].notes[0])


class TestCovers(unittest.TestCase):
    def test_mixed_closed_open_and_not_an_issue(self):
        gh = FakeGitHub(issue_states={ISSUE_A: "CLOSED", ISSUE_B: "OPEN"})
        store, fs, gh, use = _setup({
            "a.md": _entry(covers=ISSUE_A),
            "b.md": _entry(covers=ISSUE_B),
            "c.md": _entry(covers="https://github.com/x/y/pull/9"),
        }, gh)
        rows = _rows(use.execute(time.time()))
        self.assertIn("covers-closed", [f.name for f in rows["a"].flags])
        self.assertIn("closed upstream", [f for f in rows["a"].flags if f.name == "covers-closed"][0].evidence)
        self.assertNotIn("covers-closed", [f.name for f in rows["b"].flags])
        self.assertEqual(rows["b"].notes, ())
        self.assertNotIn("covers-closed", [f.name for f in rows["c"].flags])
        self.assertEqual(rows["c"].notes, ("covers is not a GitHub issue URL",))
        self.assertNotIn("https://github.com/x/y/pull/9", gh.issue_state_calls)

    def test_unreachable_github_is_unknown_after_one_call(self):
        gh = FakeGitHub(failing_calls={"issue_state"})
        store, fs, gh, use = _setup({
            "a.md": _entry(covers=ISSUE_A), "b.md": _entry(covers=ISSUE_B),
        }, gh)
        report = use.execute(time.time())
        self.assertEqual(gh.issue_state_calls, [ISSUE_A])
        for row in report.rows:
            self.assertNotIn("covers-closed", [f.name for f in row.flags])
            self.assertEqual(len(row.notes), 1)
        self.assertTrue(any("GitHub unreachable" in n for n in report.notes))

    def test_an_unexpected_state_is_unknown(self):
        gh = FakeGitHub(issue_states={ISSUE_A: "WEIRD"})
        store, fs, gh, use = _setup({"a.md": _entry(covers=ISSUE_A)}, gh)
        row = _rows(use.execute(time.time()))["a"]
        self.assertEqual(row.flags[0].name if row.flags else None, "never-delivered")
        self.assertIn("WEIRD", row.notes[0])


PIN = "lightcycle/spec-driven@466e42b44360f2ece519daf346d793768531a08e"


def _item(store, repo=None, workflow=PIN):
    item = store.create_item("t", "d", workflow=workflow)
    if repo:
        store.add_artifact(item, "repo", repo)
    return item


class TestOpportunity(unittest.TestCase):
    def _store(self, files):
        store, fs, gh, use = _setup(files)
        store.add_project("kenmclennan/lightcycle", facets=["python", "cli"])
        return store, use

    def test_opportunity_counts_matching_spawns_and_work_lists_the_project(self):
        store, use = self._store({
            "py.md": _entry(facets=["python"]), "rs.md": _entry(facets=["rust"]),
            "rv.md": _entry(steps=["review-code"]), "lc.md": _entry(steps=["lightcycle/write-code"]),
            "other.md": _entry(steps=["elsewhere/write-code"]),
        })
        item = _item(store, "kenmclennan/lightcycle")
        for _ in range(3):
            _step(store, item, "")
        report = use.execute(time.time())
        rows = _rows(report)
        self.assertEqual(rows["py"].opportunity, 3)
        self.assertEqual(rows["rs"].opportunity, 0)
        self.assertEqual(rows["rv"].opportunity, 0)
        self.assertEqual(rows["lc"].opportunity, 3)
        self.assertEqual(rows["other"].opportunity, 0)
        self.assertEqual(report.spawns, 3)
        self.assertEqual(report.projects, ({
            "project": "kenmclennan/lightcycle", "registered": True,
            "facets": ["python", "cli"], "spawns": 3,
            "steps": [{"stage": "write-code", "origin": "lightcycle", "count": 3}],
        },))

    def test_unresolvable_projects_are_listed_unregistered_with_no_facets(self):
        store, use = self._store({"any.md": _entry(), "py.md": _entry(facets=["python"])})
        _step(store, _item(store), "")
        _step(store, _item(store, "ghost/repo"), "")
        _step(store, _item(store, "kenmclennan/lightcycle"), "")
        _step(store, _item(store, "kenmclennan/lightcycle"), "")
        report = use.execute(time.time())
        rows = _rows(report)
        self.assertEqual(rows["any"].opportunity, 4)
        self.assertEqual(rows["py"].opportunity, 2)
        by = {p["project"]: p for p in report.projects}
        self.assertEqual(set(by), {None, "ghost/repo", "kenmclennan/lightcycle"})
        self.assertEqual((by[None]["registered"], by[None]["facets"]), (False, []))
        self.assertEqual((by["ghost/repo"]["registered"], by["ghost/repo"]["facets"]), (False, []))
        self.assertEqual(report.projects[0]["project"], "kenmclennan/lightcycle")

    def test_only_a_guidance_delivered_record_makes_a_spawn(self):
        store, use = self._store({"any.md": _entry()})
        item = _item(store, "kenmclennan/lightcycle")
        _step(store, item, None)
        _step(store, item, "")
        report = use.execute(time.time())
        self.assertEqual(report.spawns, 1)
        self.assertEqual(_rows(report)["any"].opportunity, 1)

    def test_since_bounds_every_count_and_a_boundary_date_is_included(self):
        store, use = self._store({"any.md": _entry()})
        item = _item(store, "kenmclennan/lightcycle")
        _step(store, item, "any", cited="any", created_at="2026-10-01T00:00:00+01:00")
        _step(store, item, "any", cited="any", created_at="2026-09-30T23:59:59+01:00")
        report = use.execute(time.time(), "2026-10-01")
        row = _rows(report)["any"]
        self.assertEqual((row.deliveries, row.citations, row.opportunity), (1, 1, 1))
        self.assertEqual((report.since, report.spawns), ("2026-10-01", 1))

    def test_since_leaves_last_delivered_and_flags_alone(self):
        store, use = self._store({"any.md": _entry()})
        item = _item(store, "kenmclennan/lightcycle")
        for _ in range(60):
            _step(store, item, "any", created_at="2026-08-01T00:00:00+00:00")
        row = _rows(use.execute(time.time(), "2026-10-01"))["any"]
        self.assertEqual(row.deliveries, 0)
        self.assertEqual(row.last_delivered, "2026-08-01T00:00:00+00:00")
        self.assertIn("unused", [f.name for f in row.flags])

    def test_no_window_reports_a_null_since(self):
        store, use = self._store({"any.md": _entry()})
        self.assertEqual(use.execute(time.time()).as_dict()["window"], {"since": None})

    def test_a_deprecated_entry_reports_its_opportunity(self):
        store, use = self._store({"old.md": _entry(status="deprecated")})
        _step(store, _item(store, "kenmclennan/lightcycle"), "")
        self.assertEqual(_rows(use.execute(time.time()))["old"].opportunity, 1)

    def test_opportunity_consults_the_delivery_matcher(self):
        store, use = self._store({"any.md": _entry()})
        _step(store, _item(store, "kenmclennan/lightcycle"), "")
        with mock.patch(
            "lightcycle.application.inspect.report_guidance.matches", return_value=False
        ) as matcher:
            row = _rows(use.execute(time.time()))["any"]
        self.assertTrue(matcher.called)
        self.assertEqual(row.opportunity, 0)


class TestParseSince(unittest.TestCase):
    def test_bad_dates_are_refused(self):
        for bad in ("2026-13-01", "10-01-2026", "2026-1-1"):
            with self.assertRaises(UseCaseError):
                parse_since(bad)

    def test_a_real_date_and_none_pass(self):
        self.assertEqual(parse_since("2026-10-01"), "2026-10-01")
        self.assertIsNone(parse_since(None))


class TestCmdGuidance(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, store, fs, argv, git):
        cli_mod.set_container(Container(
            config=_cfg(), git=git, store=store, spawner=object(), workers=object(),
            fs=fs, github=FakeGitHub(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_mod.cmd_guidance(argv) or 0
        return rc, out.getvalue(), err.getvalue()

    def test_json_prints_the_contract_shape(self):
        store, fs, gh, use = _setup({"a.md": _entry()})
        item = store.create_item("t", "d")
        _step(store, item, "a", created_at="2026-10-01T09:30:00+01:00")
        rc, out, err = self._run(store, fs, ["--json"], use._git)
        self.assertEqual(rc, 0, err)
        data = json.loads(out)
        self.assertEqual(set(data), {"window", "work", "entries", "notes"})
        entry = data["entries"][0]
        self.assertEqual(entry["id"], "a")
        self.assertEqual(entry["status"], "stable")
        self.assertEqual((entry["deliveries"], entry["citations"]), (1, 0))
        self.assertEqual(entry["last_delivered"], "2026-10-01T09:30:00+01:00")
        self.assertEqual(set(entry), {
            "id", "status", "deliveries", "citations", "opportunity", "last_delivered", "flags",
            "notes"})

    def test_text_prints_a_table(self):
        store, fs, gh, use = _setup({"a.md": _entry()})
        rc, out, err = self._run(store, fs, [], use._git)
        self.assertEqual(rc, 0, err)
        self.assertIn("LAST DELIVERED", out)
        self.assertIn("never", out)
        self.assertIn("never-delivered", out)

    def test_refuses_cleanly_without_a_guidance_repo(self):
        rc, out, err = self._run(FakeStore(), FakeFs(), ["--json"], FakeGit())
        self.assertEqual(rc, 1)
        self.assertIn("no guidance repo is registered", err)


if __name__ == "__main__":
    unittest.main()


class TestCmdGuidanceWindow(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, argv):
        store, fs, gh, use = _setup({"a.md": _entry(facets=["python"])})
        store.add_project("kenmclennan/lightcycle", facets=["python"])
        _step(store, _item(store, "kenmclennan/lightcycle"), "a",
              created_at="2026-10-02T09:00:00+01:00")
        cli_mod.set_container(Container(
            config=_cfg(), git=use._git, store=store, spawner=object(), workers=object(),
            fs=fs, github=FakeGitHub(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_mod.cmd_guidance(argv) or 0
        return rc, out.getvalue(), err.getvalue()

    def test_json_carries_window_work_and_opportunity(self):
        rc, out, err = self._run(["--json", "--since", "2026-10-01"])
        self.assertEqual(rc, 0, err)
        data = json.loads(out)
        self.assertEqual(data["window"], {"since": "2026-10-01"})
        self.assertEqual(data["work"]["spawns"], 1)
        self.assertEqual(data["work"]["projects"][0]["facets"], ["python"])
        self.assertEqual(data["entries"][0]["opportunity"], 1)

    def test_text_shows_window_column_and_work_block(self):
        rc, out, err = self._run(["--since", "2026-10-01"])
        self.assertEqual(rc, 0, err)
        self.assertIn("window: since 2026-10-01", out)
        self.assertIn("OPPORTUNITY", out)
        self.assertIn("work (facets as registered now)", out)
        self.assertIn("kenmclennan/lightcycle  facets: python  1 spawns: lightcycle/write-code 1", out)

    def test_an_invalid_since_exits_1(self):
        rc, out, err = self._run(["--since", "2026-13-01"])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("YYYY-MM-DD", err)
