_HEADING_PREFIX = "## Material: "


class UnknownMaterial(ValueError):
    def __init__(self, material, known):
        self.material = material
        self.known = tuple(known)
        super().__init__(
            "unknown material %r; known: %s" % (material, ", ".join(self.known) or "none"))


def _material_token(line):
    if line.startswith(_HEADING_PREFIX):
        return line[len(_HEADING_PREFIX):].strip()
    return None


def known_materials(text):
    return [t for t in (_material_token(line) for line in text.splitlines()) if t]


def material_criteria(text, material):
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _material_token(line) == material:
            start = i + 1
            break
    if start is None:
        raise UnknownMaterial(material, known_materials(text))
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end]).strip("\n")
