from __future__ import annotations

import io
import subprocess
import unittest
from contextlib import redirect_stderr
from importlib.resources import files
from unittest.mock import patch

from monad_execbench_capture.capture import CaptureError
from monad_execbench_capture.cli import detect_monad_commit, main

PIN = files("monad_execbench_capture").joinpath("pinned-monad.txt").read_text().strip()


class CaptureCliTest(unittest.TestCase):
    def test_packaged_pin_without_checkout_does_not_call_git(self):
        with (
            patch("monad_execbench_capture.cli.Path.exists", return_value=False),
            patch("monad_execbench_capture.cli.subprocess.run") as run,
        ):
            self.assertEqual(detect_monad_commit(), PIN)
            run.assert_not_called()

    def test_initialized_checkout_must_match_packaged_pin(self):
        for revision in (PIN, "b" * 40):
            result = subprocess.CompletedProcess([], 0, stdout=revision + "\n")
            with (
                patch("monad_execbench_capture.cli.Path.exists", return_value=True),
                patch(
                    "monad_execbench_capture.cli.subprocess.run", return_value=result
                ),
            ):
                if revision == PIN:
                    self.assertEqual(detect_monad_commit(), PIN)
                else:
                    with self.assertRaisesRegex(CaptureError, "differs"):
                        detect_monad_commit()

    def test_invalid_explicit_revision_fails_before_rpc(self):
        errors = io.StringIO()
        with (
            patch("monad_execbench_capture.cli.RpcClient") as rpc,
            redirect_stderr(errors),
        ):
            status = main(
                [
                    "--rpc-url",
                    "http://127.0.0.1:1",
                    "--calls",
                    "unused.json",
                    "--output",
                    "unused",
                    "--monad-commit",
                    "main",
                ]
            )
        self.assertEqual(status, 1)
        self.assertIn("full lowercase Git revision", errors.getvalue())
        rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
