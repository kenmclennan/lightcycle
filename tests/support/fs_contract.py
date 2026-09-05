import os


def render_frontmatter(meta):
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, dict):
            lines.append("%s:" % k)
            for sk, sv in v.items():
                lines.append("  %s: %s" % (sk, sv))
        else:
            lines.append("%s: %s" % (k, v))
    lines.append("---")
    return "\n".join(lines) + "\n"


_TAIL_CONTENT = b"aaaa\nbbbb\ncccc\n"


class FsContractBase:
    def make_fs(self, files=None, dirs=None, metas=None, bodies=None, workflows=None):
        raise NotImplementedError

    def path(self, relpath):
        raise NotImplementedError

    def root(self):
        raise NotImplementedError

    def test_exists_true_for_seeded_file(self):
        fs = self.make_fs(files={"a.txt": b"hi"})
        self.assertTrue(fs.exists(self.path("a.txt")))

    def test_exists_false_for_missing_path(self):
        fs = self.make_fs()
        self.assertFalse(fs.exists(self.path("missing.txt")))

    def test_read_bytes_returns_seeded_content(self):
        fs = self.make_fs(files={"a.txt": b"hello"})
        self.assertEqual(fs.read_bytes(self.path("a.txt")), b"hello")

    def test_iter_lines_splits_seeded_content(self):
        fs = self.make_fs(files={"a.txt": b"one\ntwo\nthree"})
        self.assertEqual(list(fs.iter_lines(self.path("a.txt"))), ["one\n", "two\n", "three"])

    def test_read_from_offset(self):
        fs = self.make_fs(files={"a.txt": b"0123456789"})
        data, offset = fs.read_from(self.path("a.txt"), 3)
        self.assertEqual(data, b"3456789")
        self.assertEqual(offset, 10)

    def test_read_tail_max_bytes_at_or_above_file_size(self):
        fs = self.make_fs(files={"a.txt": _TAIL_CONTENT})
        data, offset = fs.read_tail(self.path("a.txt"), 100)
        self.assertEqual(data, _TAIL_CONTENT)
        self.assertEqual(offset, len(_TAIL_CONTENT))

    def test_read_tail_max_bytes_on_line_boundary(self):
        fs = self.make_fs(files={"a.txt": _TAIL_CONTENT})
        data, offset = fs.read_tail(self.path("a.txt"), 10)
        self.assertEqual(data, b"bbbb\ncccc\n")
        self.assertEqual(offset, len(_TAIL_CONTENT))

    def test_read_tail_max_bytes_lands_mid_line(self):
        fs = self.make_fs(files={"a.txt": _TAIL_CONTENT})
        data, offset = fs.read_tail(self.path("a.txt"), 8)
        self.assertEqual(data, b"cccc\n")
        self.assertEqual(offset, len(_TAIL_CONTENT))

    def test_read_tail_max_bytes_too_small_for_a_complete_line(self):
        fs = self.make_fs(files={"a.txt": _TAIL_CONTENT})
        data, offset = fs.read_tail(self.path("a.txt"), 2)
        self.assertEqual(data, b"")
        self.assertEqual(offset, len(_TAIL_CONTENT))

    def test_list_dir_returns_only_subdirectories_sorted(self):
        fs = self.make_fs(files={"d/file.txt": b"x"}, dirs={"d": ["sub", "another"]})
        self.assertEqual(fs.list_dir(self.path("d")), ["another", "sub"])

    def test_worktrees_dir_joins_dot_worktrees(self):
        fs = self.make_fs()
        root = self.root()
        self.assertTrue(fs.worktrees_dir(root).endswith("/.worktrees"))
        self.assertTrue(fs.worktrees_dir(root).startswith(root))

    def test_step_roles_lists_seeded_roles_sorted(self):
        fs = self.make_fs(metas={"build": {"step": "build"}, "review": {"step": "review"}})
        self.assertEqual(fs.step_roles(self.root()), ["build", "review"])

    def test_parse_step_returns_meta_and_body(self):
        fs = self.make_fs(
            metas={"build": {"step": "build", "phase": "code"}},
            bodies={"build": "do the thing"},
        )
        parsed = fs.parse_step("build", self.root())
        self.assertEqual(parsed["meta"], {"step": "build", "phase": "code"})
        self.assertEqual(parsed["body"], "do the thing")

    def test_parse_step_unknown_role_returns_none(self):
        fs = self.make_fs(metas={"build": {"step": "build"}})
        self.assertIsNone(fs.parse_step("missing", self.root()))

    def test_workflow_text_returns_seeded_text(self):
        fs = self.make_fs(workflows={"main": "---\nentry: build\n---\nbody text\n"})
        self.assertEqual(fs.workflow_text("main", self.root()), "---\nentry: build\n---\nbody text\n")

    def test_workflow_meta_parses_frontmatter(self):
        fs = self.make_fs(workflows={"main": "---\nentry: build\n---\nbody text\n"})
        self.assertEqual(fs.workflow_meta("main", self.root()), {"entry": "build"})

    def test_workflow_names_lists_seeded_workflows_sorted(self):
        fs = self.make_fs(workflows={"b": "b text\n", "a": "a text\n"})
        self.assertEqual(fs.workflow_names(self.root()), ["a", "b"])

    def test_store_ready_false_when_store_marker_absent(self):
        fs = self.make_fs()
        self.assertFalse(fs.store_ready())

    def test_store_ready_true_when_store_marker_present(self):
        fs = self.make_fs(files={"store.db": b""})
        self.assertTrue(fs.store_ready())

    def test_ensure_logs_dir_and_append_run_log_agree_on_target(self):
        fs = self.make_fs()
        fs.ensure_logs_dir()
        fs.append_run_log("first\n")
        fs.append_run_log("second\n")
        log_path = os.path.join(fs.ensure_logs_dir(), "run.log")
        self.assertEqual(list(fs.iter_lines(log_path)), ["first\n", "second\n"])
