from lightcycle.ports.gh_shim import GhShimPort


class FakeGhShim(GhShimPort):
    def __init__(self):
        self.installs = 0

    def install(self):
        self.installs += 1
        return "/fake/shims"
