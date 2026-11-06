from lightcycle.ports.github import ReadFailure


class StackLayers:
    def __init__(self, github):
        self._github = github

    def read(self, stack_url):
        layers = self._github.stack_view(stack_url)
        if isinstance(layers, ReadFailure):
            first_line = (layers.stderr or "").strip().split("\n")[0]
            return {
                "stack_error": "stack read failed (exit %s): %s" % (layers.returncode, first_line)
            }
        return {
            "stack_layers": [
                {
                    "number": layer.number, "url": layer.url, "head_ref": layer.head_ref,
                    "base_ref": layer.base_ref, "head_sha": layer.head_sha, "state": layer.state,
                }
                for layer in layers
            ]
        }
