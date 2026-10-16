import os

from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.application.services.engine_fragments import with_engine_fragments


class _Cfg:
    def prompts_root(self):
        return "/engine"


def test_bundle_root_precedes_the_engine_root():
    assert with_engine_fragments("/bundle", _Cfg()) == ["/bundle", "/engine"]


def test_no_root_or_no_config_passes_through():
    assert with_engine_fragments(None, _Cfg()) is None
    assert with_engine_fragments("/bundle", None) == "/bundle"


def _write(root, relpath, text):
    path = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class _RealCfg:
    def __init__(self, engine):
        self._engine = engine

    def prompts_root(self):
        return self._engine


def test_bundle_step_meta_wins_over_the_engine_step(tmp_path):
    engine, bundle = str(tmp_path / "engine"), str(tmp_path / "bundle")
    _write(engine, "steps/audit.md", "---\nmodel: haiku\n---\n\nengine\n")
    _write(bundle, "steps/audit.md", "---\nmodel: opus\n---\n\nbundle\n")
    roots = with_engine_fragments(bundle, _RealCfg(engine))
    parsed = WorkflowBundleAdapter().parse_step("audit", roots)
    assert parsed.meta["model"] == "opus"
    assert "bundle" in parsed.body


def test_engine_only_include_still_expands_in_a_bundle_step(tmp_path):
    engine, bundle = str(tmp_path / "engine"), str(tmp_path / "bundle")
    _write(engine, "fragments/rule.md", "engine rule\n")
    _write(bundle, "steps/audit.md", "---\nmodel: opus\n---\n\n@include rule\n")
    roots = with_engine_fragments(bundle, _RealCfg(engine))
    parsed = WorkflowBundleAdapter().parse_step("audit", roots)
    assert "engine rule" in parsed.body
