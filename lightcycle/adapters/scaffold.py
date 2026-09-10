import os

from lightcycle.ports.scaffold import ScaffoldPort


def write_text(path, content):
    with open(path, "w") as f:
        f.write(content)


def make_dir(path):
    os.makedirs(path, exist_ok=True)


def is_dir(path):
    return os.path.isdir(path)


class ScaffoldAdapter(ScaffoldPort):
    def write_text(self, path, content):
        return write_text(path, content)

    def make_dir(self, path):
        return make_dir(path)

    def is_dir(self, path):
        return is_dir(path)
