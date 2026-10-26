"""Original fixtures exercise documented OpenFAST formats, without OpenFAST."""

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from nova.adapters.base import AdapterConfiguration, AdapterError, execute_adapter
from nova.adapters.openfast import (
    OpenFASTAdapter,
    copy_openfast_case,
    inspect_openfast_case,
    read_openfast_bytes,
    read_openfast_output,
)
from nova.adapters.process import ProcessFailure

ASCII = b"NOVA original fixture\nTime RotorPwr Angle\n(s) (kW) (deg)\n0 10 -2\n0.5 12 -1\n"


def binary(fmt):
    width = 16 if fmt == 4 else 10
    data = struct.pack("<h", fmt) + (struct.pack("<h", width) if fmt == 4 else b"")
    data += struct.pack("<ii", 2, 2) + (
        struct.pack("<dd", 2.0, 0.0) if fmt == 1 else struct.pack("<dd", 0.0, 0.5)
    )
    if fmt != 3:
        data += struct.pack("<ffff", 2.0, 4.0, 0.0, 0.0)
    data += struct.pack("<i", 4) + b"NOVA"
    for labels in [("Time", "RotorPwr", "Angle"), ("(s)", "(kW)", "(deg)")]:
        data += b"".join(s.encode().ljust(width) for s in labels)
    if fmt == 1:
        data += struct.pack("<ii", 0, 1)
    data += (
        struct.pack("<dddd", 10.0, -2.0, 12.0, -1.0)
        if fmt == 3
        else struct.pack("<hhhh", 20, -8, 24, -4)
    )
    return data


class OpenFASTTests(unittest.TestCase):
    def test_formats_preserve_data_metadata_and_hash(self):
        for fmt in (None, 1, 2, 3, 4):
            data = ASCII if fmt is None else binary(fmt)
            result = read_openfast_bytes(data, "fixture.out" if fmt is None else "fixture.outb")
            self.assertEqual(result["time_s"], [0, 0.5])
            self.assertEqual(result["values"], [[10, -2], [12, -1]])
            self.assertEqual(result["channels"][0]["units"], "(kW)")
            self.assertEqual(result["channels"][0]["frame"], "unspecified")
            self.assertEqual(result["source"]["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(result["source"]["file_id"], fmt)
        self.assertEqual(
            read_openfast_bytes(ASCII.replace(b"0.5", b"5D-1"), "a.out")["time_s"], [0, 0.5]
        )

    def test_bad_files(self):
        fixtures = [
            (b"bad", "a.out"),
            (ASCII.replace(b"(s)", b"(ms)"), "a.out"),
            (ASCII.replace(b"0.5", b"0"), "a.out"),
            (ASCII.replace(b"10 -2", b"nan -2"), "a.out"),
            (ASCII.replace(b"10 -2", b"10"), "a.out"),
            (b"\x05\x00", "a.outb"),
            (binary(2)[:-1], "a.outb"),
            (binary(4) + b"x", "a.outb"),
        ]
        for data, name in fixtures:
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                read_openfast_bytes(data, name)
        data = bytearray(binary(2))
        data[26:30] = struct.pack("<f", 0.0)
        with self.assertRaises(ValueError):
            read_openfast_bytes(bytes(data), "a.outb")

    def case(self, root):
        source = root / "inputs"
        source.mkdir()
        (source / "sub").mkdir()
        (source / "main.fst").write_text('"sub/section.dat" AeroFile\n')
        (source / "sub/section.dat").write_text("original section\n")
        (source / "main.out").write_bytes(ASCII)
        return {
            "case_directory": str(source),
            "input_file": "main.fst",
            "output_file": "main.out",
            "timeout_seconds": 2,
        }

    def program(self, root, failure=False):
        program = root / "selected solver"
        body = "raise SystemExit(7)" if failure else f"Path('case/main.out').write_bytes({ASCII!r})"
        program.write_text(
            "#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n"
            "if sys.argv[1:] == ['-v']:\n print('OpenFAST-v4.1.1')\n raise SystemExit(0)\n"
            "assert sys.argv[1:] == ['case/main.fst']\n" + body + "\n"
        )
        program.chmod(0o755)
        return AdapterConfiguration(program)

    def test_freeze_execution_and_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = self.case(root)
            config = self.program(root)
            adapter = OpenFASTAdapter()
            self.assertEqual(adapter.probe(config)["version"], "4.1.1")
            frozen = copy_openfast_case(case, root / "snapshot")
            self.assertFalse((root / "snapshot/main.out").exists())
            (root / "inputs/main.fst").write_text("changed source after submission")
            output = execute_adapter(adapter, config, frozen, root / "runs")
            self.assertEqual(output["data"]["values"], [[10, -2], [12, -1]])
            self.assertEqual(
                output["provenance"]["input_files"]["case/main.fst"],
                frozen["input_hashes"]["main.fst"],
            )
            self.assertEqual(read_openfast_output(root / "inputs/main.out")["time_s"], [0, 0.5])

    def test_isolation_probe_and_execution_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = self.case(root)
            config = self.program(root, True)
            adapter = OpenFASTAdapter()
            with self.assertRaises(ProcessFailure):
                execute_adapter(adapter, config, case, root / "runs")
            self.assertTrue(next((root / "runs").glob("*/failure.json")).is_file())
            for text in ['"../../outside.dat" AeroFile', '"/etc/passwd" File']:
                (root / "inputs/main.fst").write_text(text)
                with self.assertRaises(AdapterError):
                    adapter.validate(case, config)
            (root / "inputs/main.fst").write_text("normal")
            (root / "inputs/link").symlink_to("/etc/passwd")
            with self.assertRaises(AdapterError):
                adapter.validate(case, config)
            self.assertFalse(adapter.probe(AdapterConfiguration(root / "absent"))["available"])

    def test_snapshot_tamper_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = self.case(root)
            adapter = OpenFASTAdapter()
            config = self.program(root)
            with self.assertRaises(AdapterError):
                adapter.validate({**case, "timeout_seconds": 3601}, config)
            with self.assertRaises(AdapterError):
                adapter.validate({**case, "input_file": "../main.fst"}, config)
            frozen = copy_openfast_case(case, root / "snapshot")
            (root / "snapshot/sub/section.dat").write_text("tampered snapshot")
            with self.assertRaises(AdapterError):
                adapter.validate(frozen, config)
        header = struct.pack("<hiidd", 2, 4097, 1, 0.0, 1.0)
        with self.assertRaises(ValueError):
            read_openfast_bytes(header, "large.outb")

    def test_probe_rejects_unidentified_program_and_old_output_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = self.case(root)
            program = root / "program"
            program.write_text('#!/bin/sh\nif [ "$1" = "-v" ]; then echo other-tool; fi\n')
            program.chmod(0o755)
            config = AdapterConfiguration(program)
            adapter = OpenFASTAdapter()
            self.assertTrue(adapter.probe(config)["available"])
            self.assertFalse(adapter.probe(config)["compatible"])
            program.write_text('#!/bin/sh\nif [ "$1" = "-v" ]; then echo OpenFAST-v4.1.1; fi\n')
            with self.assertRaises(AdapterError):
                execute_adapter(adapter, config, case, root / "runs")

    def test_inspect_without_solver_reports_contained_inventory_and_hashes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = self.case(root)
            with patch('subprocess.Popen', side_effect=AssertionError('Preflight must not execute')):
                summary = inspect_openfast_case(case)
            self.assertEqual(summary['input_file'], 'main.fst')
            self.assertEqual(summary['output_file'], 'main.out')
            self.assertEqual(summary['file_count'], 2)
            self.assertEqual([f['path'] for f in summary['input_files']], ['main.fst', 'sub/section.dat'])
            self.assertEqual(summary['total_bytes'], sum(f['bytes'] for f in summary['input_files']))
            self.assertTrue(summary['warnings'])
            self.assertTrue(all(len(f['sha256']) == 64 for f in summary['input_files']))
            frozen = copy_openfast_case(case, root / 'snapshot')
            self.assertEqual(inspect_openfast_case(frozen)['case_hash'], summary['case_hash'])
            (root / 'inputs/sub/section.dat').write_text('changed source')
            self.assertNotEqual(inspect_openfast_case(case)['case_hash'], summary['case_hash'])
            self.assertEqual(inspect_openfast_case(frozen)['case_hash'], summary['case_hash'])
            (root / 'snapshot/sub/section.dat').write_text('tampered snapshot')
            with self.assertRaises(AdapterError):
                inspect_openfast_case(frozen)


if __name__ == "__main__":
    unittest.main()
