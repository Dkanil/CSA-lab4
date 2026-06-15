import argparse
import struct
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from enum import IntEnum, unique

from isa import (
    CODE_BASE,
    IN_PORT,
    OUT_PORT,
    WORD_MASK,
    decode_arg,
    decode_opcode,
    decode_operand,
    to_signed32,
)
from microcode import (
    DECODER,
    MROM,
    MROM_DESC,
    MROM_LABEL,
    AluControl,
    CondCode,
    SelAluL,
    SelAluR,
    SelAr,
    SelPc,
)

SIGN_BIT = 0x80000000


@unique
class SelMpc(IntEnum):
    NEXT = 0
    ADDR = 1
    DECODE = 2


class MachineError(Exception):
    pass


class InputBufferEmpty(MachineError):
    pass


@dataclass
class CpuState:
    tick: int
    mpc: int
    pc: int
    ar: int
    dr: int
    acc: int
    z: bool
    n: bool


class Memory:
    def __init__(self, words: list[int], input_buffer: list[int]) -> None:
        self.words = [word & WORD_MASK for word in words]
        self.input_buffer = deque(word & WORD_MASK for word in input_buffer)
        self.output_buffer: list[int] = []

    def _ensure_address(self, address: int) -> None:
        if address < 0:
            raise MachineError(f"negative memory address: {address}")
        if address >= len(self.words):
            self.words.extend([0] * (address - len(self.words) + 1))

    def read(self, address: int) -> int:
        if address == IN_PORT:
            if not self.input_buffer:
                raise InputBufferEmpty("input buffer is empty")
            return self.input_buffer.popleft()
        self._ensure_address(address)
        return self.words[address]

    def write(self, address: int, value: int) -> None:
        value &= WORD_MASK
        if address == OUT_PORT:
            self.output_buffer.append(value)
            return
        self._ensure_address(address)
        self.words[address] = value


class DataPath:
    def __init__(self, memory: Memory, entry: int = CODE_BASE) -> None:
        self.memory = memory
        self.pc = entry & WORD_MASK
        self.ar = entry & WORD_MASK
        self.dr = 0
        self.acc = 0
        self.z = False
        self.n = False

    def snapshot(self, tick: int, mpc: int) -> CpuState:
        return CpuState(
            tick=tick,
            mpc=mpc,
            pc=self.pc,
            ar=self.ar,
            dr=self.dr,
            acc=self.acc,
            z=self.z,
            n=self.n,
        )


class ControlUnit:
    def __init__(self, datapath: DataPath) -> None:
        self.datapath = datapath
        self.mpc = 0
        self.tick = 0
        self.executed_instructions = 0
        self.halted = False
        self.stop_reason = ""

    def step(self) -> int:
        if self.halted:
            return self.mpc

        if self.mpc < 0 or self.mpc >= len(MROM):
            raise MachineError(f"MPC is outside microcode memory: {self.mpc}")

        dp = self.datapath
        mpc = self.mpc
        micro = MROM[mpc]
        self.tick += 1

        old_dr = dp.dr
        old_z = dp.z
        old_n = dp.n
        result = self._alu_result(micro.sel_alu_l, micro.sel_alu_r, micro.alu_control)

        memory_output = dp.dr
        if micro.mem_r:
            memory_output = dp.memory.read(dp.ar)

        if micro.mem_wr:
            dp.memory.write(dp.ar, result)

        if micro.pc_l:
            if micro.sel_pc == SelPc.INC:
                dp.pc = (dp.pc + 1) & WORD_MASK
            elif micro.sel_pc == SelPc.ALU:
                dp.pc = result & WORD_MASK
            else:
                raise MachineError(f"unknown PC mux selector: {micro.sel_pc}")

        if micro.dr_l:
            dp.dr = memory_output & WORD_MASK

        if micro.ar_l:
            if micro.sel_ar == SelAr.PC:
                dp.ar = dp.pc & WORD_MASK
            elif micro.sel_ar == SelAr.ARG:
                dp.ar = decode_operand(dp.dr)
            elif micro.sel_ar == SelAr.DR:
                dp.ar = dp.dr & WORD_MASK
            else:
                raise MachineError(f"unknown AR mux selector: {micro.sel_ar}")

        if micro.acc_l:
            dp.acc = result & WORD_MASK

        if micro.flags_l:
            value = result & WORD_MASK
            dp.z = value == 0
            dp.n = (value & SIGN_BIT) != 0

        if micro.halted:
            self.halted = True
            self.stop_reason = "halt"

        if micro.cond_code == CondCode.DECODE:
            self.executed_instructions += 1

        sel_mpc = self._select_mpc(micro.cond_code, old_z, old_n)
        self.mpc = self._mux_mpc(sel_mpc, micro.jmp_addr, old_dr, mpc)
        return mpc

    def _select_mpc(self, cond_code: CondCode, z: bool, n: bool) -> SelMpc:
        if cond_code == CondCode.NEXT:
            return SelMpc.NEXT
        if cond_code == CondCode.ALWAYS:
            return SelMpc.ADDR
        if cond_code == CondCode.DECODE:
            return SelMpc.DECODE
        if cond_code == CondCode.EQ:
            return SelMpc.ADDR if z else SelMpc.NEXT
        if cond_code == CondCode.NE:
            return SelMpc.ADDR if not z else SelMpc.NEXT
        if cond_code == CondCode.LT:
            return SelMpc.ADDR if n else SelMpc.NEXT
        if cond_code == CondCode.GT:
            return SelMpc.ADDR if not n and not z else SelMpc.NEXT
        if cond_code == CondCode.LE:
            return SelMpc.ADDR if n or z else SelMpc.NEXT
        if cond_code == CondCode.GE:
            return SelMpc.ADDR if not n else SelMpc.NEXT
        raise MachineError(f"unknown condition code: {cond_code}")

    def _mux_mpc(
        self, sel_mpc: SelMpc, next_addr: int, decode_word: int, mpc: int
    ) -> int:
        if sel_mpc == SelMpc.NEXT:
            return mpc + 1
        if sel_mpc == SelMpc.ADDR:
            return next_addr
        if sel_mpc == SelMpc.DECODE:
            try:
                opcode = decode_opcode(decode_word)
            except ValueError as exc:
                raise MachineError(str(exc)) from exc
            return DECODER[opcode]
        raise MachineError(f"unknown MPC mux selector: {sel_mpc}")

    def _instruction_arg(self) -> int:
        try:
            return decode_arg(self.datapath.dr)
        except ValueError as exc:
            raise MachineError(str(exc)) from exc

    def _alu_result(self, left_sel: SelAluL, right_sel: SelAluR, op: AluControl) -> int:
        left = self._alu_left(left_sel)
        right = self._alu_right(right_sel)

        if op == AluControl.PASS_LEFT:
            return left & WORD_MASK
        if op == AluControl.PASS_RIGHT:
            return right & WORD_MASK
        if op == AluControl.ADD:
            return (left + right) & WORD_MASK
        if op == AluControl.SUB:
            return (left - right) & WORD_MASK
        if op == AluControl.MUL:
            return (to_signed32(left) * to_signed32(right)) & WORD_MASK
        if op == AluControl.DIV:
            divisor = to_signed32(right)
            if divisor == 0:
                raise MachineError("division by zero")
            return (to_signed32(left) // divisor) & WORD_MASK
        if op == AluControl.MOD:
            divisor = to_signed32(right)
            if divisor == 0:
                raise MachineError("division by zero")
            return (to_signed32(left) % divisor) & WORD_MASK
        if op == AluControl.NEG:
            return (-to_signed32(left)) & WORD_MASK
        raise MachineError(f"unknown ALU operation: {op}")

    def _alu_left(self, selector: SelAluL) -> int:
        if selector == SelAluL.ACC:
            return self.datapath.acc
        if selector == SelAluL.PC:
            return self.datapath.pc
        raise MachineError(f"unknown ALU left mux value: {selector}")

    def _alu_right(self, selector: SelAluR) -> int:
        if selector == SelAluR.DR:
            return self.datapath.dr
        if selector == SelAluR.ARG:
            return self._instruction_arg()
        raise MachineError(f"unknown ALU right mux value: {selector}")


def load_program(path: str | Path) -> tuple[int, list[int]]:
    raw = Path(path).read_bytes()
    if len(raw) % 4 != 0:
        raise MachineError("binary size is not aligned to 32-bit words")
    words = [word[0] for word in struct.iter_unpack(">I", raw)]
    if len(words) < 2:
        raise MachineError("binary header is missing")

    entry = words[0]
    memory_size = words[1]
    memory = words[2:]
    if len(memory) < memory_size:
        raise MachineError(
            f"memory image is truncated: expected {memory_size} words, got {len(memory)}"
        )
    return entry, memory[:memory_size]


def load_input(path: str | Path | None) -> list[int]:
    if path is None:
        return []
    return list(Path(path).read_bytes())


def format_trace_line(cu: ControlUnit, executed_mpc: int) -> str:
    dp = cu.datapath
    instruction = MROM_LABEL[executed_mpc] or "?"
    desc = MROM_DESC[executed_mpc] or "NOP"
    return (
        f"tick={cu.tick:06} mPC={executed_mpc:03} {instruction:<6} "
        f"pc={dp.pc & WORD_MASK:08X} ar={dp.ar & WORD_MASK:08X} dr={dp.dr & WORD_MASK:08X} "
        f"acc={dp.acc & WORD_MASK:08X} z={int(dp.z)} n={int(dp.n)} | {desc}"
    )


def run_until_stop(
    cu: ControlUnit,
    limit: int = 100000,
    on_step: Callable[[ControlUnit, int], None] | None = None,
) -> ControlUnit:
    while not cu.halted and cu.tick < limit:
        try:
            executed_mpc = cu.step()
        except InputBufferEmpty:
            cu.halted = True
            cu.stop_reason = "input buffer is empty"
            break
        if on_step is not None:
            on_step(cu, executed_mpc)

    if not cu.halted:
        cu.stop_reason = f"tick limit exceeded ({limit})"
    return cu


def simulate(
    program_path: str | Path,
    input_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    limit: int = 100000,
) -> ControlUnit:
    entry, memory_image = load_program(program_path)
    memory = Memory(memory_image, load_input(input_path))
    cu = ControlUnit(DataPath(memory, entry))
    trace: list[str] = []

    def append_trace(control_unit: ControlUnit, executed_mpc: int) -> None:
        trace.append(format_trace_line(control_unit, executed_mpc))

    run_until_stop(cu, limit, append_trace)

    if trace_path is not None:
        Path(trace_path).write_text("\n".join(trace), encoding="utf-8")
    return cu


def output_as_text(values: list[int]) -> str:
    chars = []
    for value in values:
        signed = to_signed32(value)
        if 32 <= signed <= 126:
            chars.append(chr(signed))
        else:
            return ""
    return "".join(chars)


def main(
    program: str | None = None,
    input_file: str | None = None,
    trace_file: str | None = None,
    limit: int = 100000,
) -> None:
    if program is None:
        parser = argparse.ArgumentParser(description="Run microcoded processor model")
        parser.add_argument(
            "program", help="binary memory image produced by translator.py"
        )
        parser.add_argument("input", nargs="?", help="optional input stream file")
        parser.add_argument("--trace", help="optional trace output file")
        parser.add_argument(
            "--limit", type=int, default=100000, help="maximum tick count"
        )
        args = parser.parse_args()
        program = args.program
        input_file = args.input
        trace_file = args.trace
        limit = args.limit

    cu = simulate(program, input_file, trace_file, limit)
    output = [to_signed32(value) for value in cu.datapath.memory.output_buffer]
    text = output_as_text(cu.datapath.memory.output_buffer)

    print(f"stop_reason: {cu.stop_reason}")
    print(f"instr: {cu.executed_instructions} ticks: {cu.tick}")
    print(f"output: {output}")
    if text:
        print(f"text: {text}")


if __name__ == "__main__":
    main()
