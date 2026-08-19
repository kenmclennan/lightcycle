from dataclasses import dataclass


@dataclass(frozen=True)
class OpenArtifactInput:
    kind: str
    value: str


@dataclass(frozen=True)
class OpenArtifactResult:
    success: bool
    message: str


class OpenArtifactUseCase:
    def __init__(self, fs, launcher):
        self._fs = fs
        self._launcher = launcher

    def execute(self, input: OpenArtifactInput) -> OpenArtifactResult:
        if input.kind == "filepath" and not self._fs.exists(input.value):
            return OpenArtifactResult(False, "%s no longer exists" % input.value)
        opened = (
            self._launcher.open_url(input.value) if input.kind == "url"
            else self._launcher.open_path(input.value)
        )
        if not opened:
            return OpenArtifactResult(False, "Could not open %s" % input.value)
        destination = "your browser" if input.kind == "url" else "its default application"
        return OpenArtifactResult(True, "Opened %s in %s" % (input.value, destination))
