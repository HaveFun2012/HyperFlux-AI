import os
import subprocess
import sys
import time
import unittest

from hyperflux.desktop.process_tree import descendant_pids, terminate_pid

# A launcher that starts a long-running child, like koboldcpp.exe's PyInstaller bootloader.
LAUNCHER = (
    "import subprocess, sys;"
    "subprocess.run([sys.executable, '-c', 'import time; time.sleep(60)'])"
)


@unittest.skipUnless(os.name == "nt", "Windows process APIs")
class ProcessTreeTests(unittest.TestCase):
    def test_stopping_child_lets_launcher_exit(self):
        launcher = subprocess.Popen([sys.executable, "-c", LAUNCHER])
        try:
            children = []
            for _ in range(50):
                children = descendant_pids(launcher.pid)
                if children:
                    break
                time.sleep(0.1)
            self.assertEqual(len(children), 1)
            time.sleep(0.5)  # let the launcher finish starting its child
            self.assertTrue(terminate_pid(children[0]))
            # The launcher exits by itself once its child is gone.
            self.assertIsNotNone(launcher.wait(timeout=10))
        finally:
            if launcher.poll() is None:
                launcher.kill()

    def test_process_without_children(self):
        self.assertEqual(descendant_pids(0), [])


if __name__ == "__main__":
    unittest.main()
