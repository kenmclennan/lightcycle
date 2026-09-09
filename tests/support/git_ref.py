import subprocess


def read_at_ref(ref, path):
    try:
        proc = subprocess.run(
            ["git", "show", "%s:%s" % (ref, path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return proc.stdout
