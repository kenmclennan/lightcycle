from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OpenArtifactInput:
    kind: str
    value: str
    editor: Optional[str] = None


@dataclass(frozen=True)
class OpenArtifactResult:
    success: bool
    message: str


class OpenArtifactUseCase:
    def __init__(self, fs, launcher):
        self._fs = fs
        self._launcher = launcher

    def execute(self, input: OpenArtifactInput) -> OpenArtifactResult:
        if input.kind in ("filepath", "editor") and not self._fs.exists(input.value):
            return OpenArtifactResult(False, "%s no longer exists" % input.value)
        if input.kind == "url":
            opened = self._launcher.open_url(input.value)
        elif input.kind == "editor":
            opened = self._open_in_editor(input.editor, input.value)
        else:
            opened = self._launcher.open_path(input.value)
        if not opened:
            return OpenArtifactResult(False, "Could not open %s" % input.value)
        destination = {"url": "your browser", "editor": "your editor"}.get(
            input.kind, "its default application"
        )
        return OpenArtifactResult(True, "Opened %s in %s" % (input.value, destination))

    def _open_in_editor(self, editor, path):
        try:
            self._launcher.edit(editor, path)
            return True
        except (OSError, ValueError):
            return False
