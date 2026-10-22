import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest

_CHILD = (
    "import os, signal, sqlite3, sys\n"
    "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
    "c.execute('BEGIN')\n"
    "c.execute(\"UPDATE rows SET v = 'changed' WHERE k = 1\")\n"
    "c.execute(\"INSERT INTO rows VALUES (2, 'new')\")\n"
    "os.kill(os.getpid(), signal.SIGKILL)\n"
)


class TestSigkillMidTransaction(unittest.TestCase):
    def test_a_killed_open_transaction_keeps_neither_write(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "t.db")
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE rows (k INTEGER PRIMARY KEY, v TEXT)")
            conn.execute("INSERT INTO rows VALUES (1, 'orig')")
            conn.commit()
            conn.close()

            proc = subprocess.run([sys.executable, "-I", "-c", _CHILD, path], timeout=60)

            self.assertEqual(proc.returncode, -signal.SIGKILL)
            check = sqlite3.connect(path)
            self.assertEqual(check.execute("SELECT k, v FROM rows").fetchall(), [(1, "orig")])
            check.close()


if __name__ == "__main__":
    unittest.main()
