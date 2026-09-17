import unittest

from tests.support.tui_display_guard import Violation, WidgetIdentity, find_violations


class TestComposeTimeGuard(unittest.TestCase):
    def test_widget_set_before_yield_is_safe(self):
        source = """
class Foo(Widget):
    def compose(self):
        table = SomeTable(id="table")
        table.display = self._active
        yield table

    def toggle(self):
        self.query_one("#table", SomeTable).display = False
"""
        violations, unresolved = find_violations({"foo.py": source})
        self.assertEqual(violations, [])
        self.assertEqual(unresolved, [])


class TestSynchronousOnMountClosure(unittest.TestCase):
    def test_widget_safe_via_helper_two_calls_deep(self):
        source = """
class Foo(Widget):
    def compose(self):
        yield Static(id="hold")

    def on_mount(self):
        self._setup()

    def _setup(self):
        self._apply()

    def _apply(self):
        self.query_one("#hold", Static).display = False
"""
        violations, unresolved = find_violations({"foo.py": source})
        self.assertEqual(violations, [])
        self.assertEqual(unresolved, [])

    def test_deferred_only_reachability_is_still_a_violation(self):
        source = """
class Foo(Widget):
    def compose(self):
        yield Static(id="hold")

    def on_mount(self):
        self.set_interval(1, self._apply)

    def _apply(self):
        self.query_one("#hold", Static).display = False
"""
        violations, unresolved = find_violations({"foo.py": source})
        self.assertEqual(
            violations, [Violation("foo.py", "Foo", WidgetIdentity("Static", "hold"))]
        )
        self.assertEqual(unresolved, [])


class TestCssDefault(unittest.TestCase):
    def test_widget_safe_via_css_default(self):
        source = """
class Foo(Widget):
    CSS = \"\"\"
    #hold {
        display: none;
    }
    \"\"\"

    def compose(self):
        yield Static(id="hold")

    def toggle(self):
        self.query_one("#hold", Static).display = True
"""
        violations, unresolved = find_violations({"foo.py": source})
        self.assertEqual(violations, [])
        self.assertEqual(unresolved, [])


class TestNestedContainerExtraction(unittest.TestCase):
    def test_widget_nested_in_container_is_tracked(self):
        source = """
class Foo(Widget):
    def compose(self):
        yield Horizontal(
            Static(id="left"),
            Static(id="right"),
            id="bar",
        )

    def toggle(self):
        self.query_one("#right", Static).display = False
"""
        violations, unresolved = find_violations({"foo.py": source})
        self.assertEqual(
            violations, [Violation("foo.py", "Foo", WidgetIdentity("Static", "right"))]
        )
        self.assertEqual(unresolved, [])


class TestUnresolvedSite(unittest.TestCase):
    def test_non_literal_selector_is_reported_unresolved_not_passed(self):
        source = """
class Foo(Widget):
    def compose(self):
        yield Static(id="hold")

    def _line(self, selector):
        widget = self.query_one(selector, Static)
        widget.display = False
"""
        violations, unresolved = find_violations({"foo.py": source})
        self.assertEqual(violations, [])
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].file, "foo.py")
        self.assertEqual(unresolved[0].cls, "Foo")
