import ast
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOMAIN = REPO_ROOT / "lightcycle" / "domain"
LIGHTCYCLE = REPO_ROOT / "lightcycle"
APPLICATION = LIGHTCYCLE / "application"
PORTS = LIGHTCYCLE / "ports"
ADAPTERS = LIGHTCYCLE / "adapters"
ADAPTERS_TUI = ADAPTERS / "tui"
CLI = LIGHTCYCLE / "cli.py"

BD_MARKERS = ('"Issue"', "issue_type", "close_reason", "dependency_count")
ALLOW = set()

BANNED_ADAPTER_IMPORTS = ("subprocess", "urllib", "sqlite3")
BANNED_ADAPTER_IMPORT_ALLOW = set()

DOMAIN_BANNED_IMPORTS = (
    "lightcycle.application", "lightcycle.adapters", "lightcycle.ports",
    "lightcycle.cli", "lightcycle.container",
)
APPLICATION_BANNED_IMPORTS = ("lightcycle.adapters", "lightcycle.container")
PORTS_BANNED_IMPORTS = ("lightcycle.application", "lightcycle.adapters")
DRIVEN_ADAPTER_BANNED_IMPORTS = ("lightcycle.application", "lightcycle.container")

DRIVEN_ADAPTER_IMPORT_EXEMPT = {
    ADAPTERS / "upgrade.py":
        "imports plain exception types and a pure helper from application/setup/upgrade.py; "
        "LC-594 scoped this deliberately, per F-32's convention - lc show LC-594 or read its "
        "spec for the reasoning",
}


def _imported_modules(tree):
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def find_banned_imports(tree, banned_prefixes):
    offenders = []
    for module in _imported_modules(tree):
        for prefix in banned_prefixes:
            if module == prefix or module.startswith(prefix + "."):
                offenders.append(module)
                break
    return offenders


class TestDomainSpeaksNoBead(unittest.TestCase):
    def test_no_bd_wire_format_in_domain(self):
        offenders = []
        for path in sorted(DOMAIN.rglob("*.py")):
            if path.name in ALLOW:
                continue
            text = path.read_text()
            for marker in BD_MARKERS:
                if marker in text:
                    offenders.append("%s: %s" % (path.relative_to(DOMAIN), marker))
        self.assertEqual(offenders, [], "bd wire-format leaked into the domain: %s" % offenders)


class TestApplicationImportsNoAdapterTech(unittest.TestCase):
    def test_no_subprocess_urllib_sqlite3_imports(self):
        offenders = []
        paths = sorted(APPLICATION.rglob("*.py")) + [CLI]
        for path in paths:
            if path in BANNED_ADAPTER_IMPORT_ALLOW:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module.split(".")[0]] if node.module else []
                else:
                    continue
                for name in names:
                    if name in BANNED_ADAPTER_IMPORTS:
                        offenders.append("%s: %s" % (path.relative_to(REPO_ROOT), name))
        self.assertEqual(
            offenders, [], "adapter exception types crossing the port boundary: %s" % offenders
        )


class TestFindBannedImports(unittest.TestCase):
    def test_flags_a_banned_application_import(self):
        tree = ast.parse("from lightcycle.application.something import Thing\n")
        offenders = find_banned_imports(tree, DRIVEN_ADAPTER_BANNED_IMPORTS)
        self.assertEqual(offenders, ["lightcycle.application.something"])

    def test_does_not_flag_an_unrelated_import(self):
        tree = ast.parse("from lightcycle.domain.something import Thing\n")
        offenders = find_banned_imports(tree, DRIVEN_ADAPTER_BANNED_IMPORTS)
        self.assertEqual(offenders, [])


class TestDomainImportsNothingAboveIt(unittest.TestCase):
    def test_no_application_adapters_ports_cli_or_container_imports(self):
        offenders = []
        for path in sorted(DOMAIN.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for module in find_banned_imports(tree, DOMAIN_BANNED_IMPORTS):
                offenders.append("%s: %s" % (path.relative_to(REPO_ROOT), module))
        self.assertEqual(offenders, [], "domain imports above its own layer: %s" % offenders)


class TestApplicationImportsNoAdaptersOrContainer(unittest.TestCase):
    def test_no_adapters_or_container_imports(self):
        offenders = []
        for path in sorted(APPLICATION.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for module in find_banned_imports(tree, APPLICATION_BANNED_IMPORTS):
                offenders.append("%s: %s" % (path.relative_to(REPO_ROOT), module))
        self.assertEqual(
            offenders, [], "application imports adapters or the container: %s" % offenders
        )


class TestPortsImportNoApplicationOrAdapters(unittest.TestCase):
    def test_no_application_or_adapters_imports(self):
        offenders = []
        for path in sorted(PORTS.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for module in find_banned_imports(tree, PORTS_BANNED_IMPORTS):
                offenders.append("%s: %s" % (path.relative_to(REPO_ROOT), module))
        self.assertEqual(offenders, [], "ports import application or adapters: %s" % offenders)


class TestDrivenAdaptersImportNoApplication(unittest.TestCase):
    def test_no_application_imports(self):
        offenders = []
        for path in sorted(ADAPTERS.rglob("*.py")):
            if ADAPTERS_TUI in path.parents:
                continue
            if path in DRIVEN_ADAPTER_IMPORT_EXEMPT:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for module in find_banned_imports(tree, DRIVEN_ADAPTER_BANNED_IMPORTS):
                offenders.append("%s: %s" % (path.relative_to(REPO_ROOT), module))
        self.assertEqual(
            offenders, [], "a driven adapter imports the application layer: %s" % offenders
        )


class TestStoreFilenameHasOneDefinition(unittest.TestCase):
    def test_store_db_literal_appears_once(self):
        sites = []
        for path in sorted(LIGHTCYCLE.rglob("*.py")):
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if '"store.db"' in line:
                    sites.append("%s:%d" % (path.relative_to(LIGHTCYCLE), lineno))
        self.assertEqual(len(sites), 1, "store.db respelled outside its constant: %s" % sites)
        self.assertEqual(sites[0].split(":")[0], "adapters/fsio.py")


class TestNoSpecLiteralInEngineCore(unittest.TestCase):
    def test_no_spec_artifact_type_literal_in_domain_or_application(self):
        offenders = []
        for root in (DOMAIN, APPLICATION):
            for path in sorted(root.rglob("*.py")):
                for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                    if '"spec"' in line:
                        offenders.append("%s:%d" % (path.relative_to(REPO_ROOT), lineno))
        self.assertEqual(offenders, [], "literal \"spec\" found in engine core: %s" % offenders)


class TestHookLiteralsHaveOneDefinition(unittest.TestCase):
    def test_hook_literals_appear_only_in_hooks_module(self):
        tokens = ('"pr_merge"', '"pr_feedback"', '"pr_conflict"', '"ci_failed_cap"')
        offenders = []
        for path in sorted(LIGHTCYCLE.rglob("*.py")):
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                for token in tokens:
                    if token in line:
                        offenders.append("%s:%d: %s" % (path.relative_to(LIGHTCYCLE), lineno, token))
        allowed = "domain/flow/hooks.py"
        offenders = [o for o in offenders if not o.startswith(allowed + ":")]
        self.assertEqual(offenders, [], "hook literal respelled outside %s: %s" % (allowed, offenders))


if __name__ == "__main__":
    unittest.main()
