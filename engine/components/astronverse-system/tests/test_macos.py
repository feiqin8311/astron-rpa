import sys
import unittest

from astronverse.system.core.printer_core import (
    parse_lpstat_default,
    parse_lpstat_jobs_idle,
    parse_lpstat_printers,
    parse_lpstat_status,
)
from astronverse.system.core.process_core import escape_osascript_shell


class TestMacosImports(unittest.TestCase):
    def test_import_system_modules(self):
        import astronverse.system.clipboard
        import astronverse.system.compress
        import astronverse.system.file
        import astronverse.system.folder
        import astronverse.system.process
        import astronverse.system.system

        assert astronverse.system.system
        assert astronverse.system.clipboard
        assert astronverse.system.folder
        assert astronverse.system.process
        assert astronverse.system.file
        assert astronverse.system.compress


class TestLpstatParse(unittest.TestCase):
    SAMPLE = (
        "printer HP_LaserJet is idle.  enabled since Sat Oct  3 10:00:00 2026\n"
        "printer Office_Printer disabled since Sat Oct  3 09:00:00 2026 -\n"
        "        reason unknown\n"
        "system default destination: HP_LaserJet\n"
    )

    def test_parse_printers(self):
        assert parse_lpstat_printers(self.SAMPLE) == ["HP_LaserJet", "Office_Printer"]

    def test_parse_default(self):
        assert parse_lpstat_default(self.SAMPLE) == "HP_LaserJet"

    def test_parse_default_missing(self):
        assert parse_lpstat_default("no system default destination") == ""

    def test_parse_empty(self):
        assert parse_lpstat_printers("") == []
        assert parse_lpstat_default("") == ""

    def test_parse_status_and_jobs(self):
        assert parse_lpstat_status(self.SAMPLE) == 0
        assert parse_lpstat_status("printer HP_LaserJet now printing HP_LaserJet-1.\n") == 1
        assert parse_lpstat_jobs_idle("") is True
        assert parse_lpstat_jobs_idle("HP_LaserJet-12  root  1024  2026-10-03") is False


class TestOsascriptEscape(unittest.TestCase):
    def test_plain(self):
        assert escape_osascript_shell("echo hello") == "echo hello"

    def test_quotes(self):
        assert escape_osascript_shell('echo "hi"') == r"echo \"hi\""

    def test_backslash(self):
        assert escape_osascript_shell(r"echo a\b") == r"echo a\\b"

    def test_combined(self):
        assert escape_osascript_shell(r'cd "C:\tmp" && ls') == r"cd \"C:\\tmp\" && ls"


@unittest.skipUnless(sys.platform == "darwin", "ProcessCoreMac only on macOS")
class TestProcessCoreMac(unittest.TestCase):
    def test_run_cmd_string_redirect(self):
        import os
        import tempfile
        from pathlib import Path

        from astronverse.system.core.process_core import ProcessCoreMac

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.txt")
            proc = ProcessCoreMac.run_cmd('echo hi > "{}"'.format(path))
            proc.wait(timeout=5)
            assert Path(path).read_text(encoding="utf-8").strip() == "hi"

    def test_run_cmd_list(self):
        import os
        import tempfile

        from astronverse.system.core.process_core import ProcessCoreMac

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "list.txt")
            proc = ProcessCoreMac.run_cmd(["touch", path])
            proc.wait(timeout=5)
            assert os.path.isfile(path)


@unittest.skipUnless(sys.platform == "darwin", "clipboard round-trip only on macOS")
class TestClipboardRoundTrip(unittest.TestCase):
    def test_text_round_trip(self):
        from astronverse.system.core.clipboard_core_mac import ClipBoardCore

        original = ClipBoardCore.paste_str_clip()
        try:
            ClipBoardCore.copy_str_clip("astronverse-macos-clipboard-test")
            assert ClipBoardCore.paste_str_clip() == "astronverse-macos-clipboard-test"
        finally:
            ClipBoardCore.copy_str_clip(original)


if __name__ == "__main__":
    unittest.main()
