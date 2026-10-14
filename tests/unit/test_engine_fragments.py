from lightcycle.application.services.engine_fragments import with_engine_fragments


class _Cfg:
    def prompts_root(self):
        return "/engine"


def test_engine_root_precedes_the_bundle_root():
    assert with_engine_fragments("/bundle", _Cfg()) == ["/engine", "/bundle"]


def test_no_root_or_no_config_passes_through():
    assert with_engine_fragments(None, _Cfg()) is None
    assert with_engine_fragments("/bundle", None) == "/bundle"
