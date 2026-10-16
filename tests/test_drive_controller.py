import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from application.config import PROJECT_ROOT


class DriveControllerTests(unittest.TestCase):
    def test_drive_sequence_and_protection(self):
        compiler = Path('C:/msys64/mingw32/bin/gcc.exe')
        env = dict(os.environ, PATH=str(compiler.parent) + os.pathsep + os.environ['PATH'])
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'drive_controller_test.exe'
            subprocess.run([str(compiler), '-O2', '-Wall', '-Wextra', '-Werror', '-static-libgcc',
                            '-o', str(executable), str(PROJECT_ROOT / 'tests/test_drive_controller.c')],
                           env=env, check=True)
            subprocess.run([str(executable)], check=True, env=env)
