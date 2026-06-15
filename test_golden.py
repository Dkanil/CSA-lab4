import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import Any

import machine
import pytest
import translator


@pytest.mark.golden_test("golden/*.yml")
def test_translator_and_machine(golden: Any) -> None:
    with tempfile.TemporaryDirectory() as tmpdirname:
        source = os.path.join(tmpdirname, "source.alg")
        input_stream = os.path.join(tmpdirname, "input.bin")
        target = os.path.join(tmpdirname, "target.bin")
        listing = target + ".lst"
        ast_dump = target + ".ast"
        trace = os.path.join(tmpdirname, "trace.log")

        Path(source).write_text(golden["in_source"], encoding="utf-8")
        Path(input_stream).write_bytes(bytes(golden["in_stdin"]))

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            translator.main(source, target)
            print("============================================================")
            machine.main(target, input_stream, trace, int(golden["in_limit"]))

        code = Path(target).read_bytes()
        code_listing = Path(listing).read_text(encoding="utf-8")
        ast_text = Path(ast_dump).read_text(encoding="utf-8")
        trace_text = Path(trace).read_text(encoding="utf-8")
        log_head_lines = golden.get("out_log_head_lines")
        if log_head_lines is not None:
            trace_text = "\n".join(trace_text.splitlines()[: int(log_head_lines)])
            if trace_text:
                trace_text += "\n"

        assert code == golden.out["out_code"]
        assert code_listing == golden.out["out_code_hex"]
        assert ast_text == golden.out["out_ast"]
        assert stdout.getvalue() == golden.out["out_stdout"]
        assert trace_text == golden.out["out_log"]
