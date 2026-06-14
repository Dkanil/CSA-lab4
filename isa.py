import struct
from dataclasses import dataclass
from enum import IntEnum, unique
from pathlib import Path

IN_PORT = 0x0000
OUT_PORT = 0x0001
CODE_BASE = 0x0002

WORD_MASK = 0xFFFFFFFF
OPERAND_MASK = 0x00FFFFFF
OPERAND_SIGN = 0x00800000


@unique
class Opcode(IntEnum):
    LD = 0x10
    LDI = 0x11
    LD_IND = 0x12
    ST = 0x13
    ST_IND = 0x14

    ADD = 0x20
    ADDI = 0x21
    SUB = 0x22
    SUBI = 0x23
    MUL = 0x24
    DIV = 0x25
    MOD = 0x26
    CMP = 0x27
    CMPI = 0x28
    NEG = 0x29

    JMP = 0x30
    BEQ = 0x31
    BNE = 0x32
    BLT = 0x33
    BGT = 0x34
    BLE = 0x35
    BGE = 0x36

    HLT = 0xFF


@dataclass
class Instruction:
    opcode: Opcode
    operand: int = 0

    def encode(self) -> int:
        return (self.opcode.value << 24) | (self.operand & OPERAND_MASK)

    def to_bytes(self) -> bytes:
        return struct.pack(">I", self.encode())

    @staticmethod
    def decode(word: int) -> "Instruction":
        opcode = Opcode((word >> 24) & 0xFF)
        operand = word & OPERAND_MASK
        if opcode in {Opcode.LDI, Opcode.ADDI, Opcode.SUBI, Opcode.CMPI} and operand & OPERAND_SIGN:
            operand -= 1 << 24
        return Instruction(opcode, operand)

    def __str__(self) -> str:
        if self.opcode in {Opcode.NEG, Opcode.HLT}:
            return self.opcode.name.lower()
        return f"{self.opcode.name.lower()} {self.operand}"


def format_address(address: int) -> str:
    if address == IN_PORT:
        return "IN_PORT"
    if address == OUT_PORT:
        return "OUT_PORT"
    return f"mem[{address}]"


def mnemonic(instruction: Instruction) -> str:
    op = instruction.opcode
    arg = instruction.operand
    addr = format_address(arg)

    if op == Opcode.LD:
        return f"ld {arg}: ACC <- {addr}"
    if op == Opcode.LDI:
        return f"ldi {arg}: ACC <- {arg}"
    if op == Opcode.LD_IND:
        return f"ld_ind {arg}: ACC <- mem[{addr}]"
    if op == Opcode.ST:
        return f"st {arg}: {addr} <- ACC"
    if op == Opcode.ST_IND:
        return f"st_ind {arg}: mem[{addr}] <- ACC"

    if op == Opcode.ADD:
        return f"add {arg}: ACC <- ACC + {addr}"
    if op == Opcode.ADDI:
        return f"addi {arg}: ACC <- ACC + {arg}"
    if op == Opcode.SUB:
        return f"sub {arg}: ACC <- ACC - {addr}"
    if op == Opcode.SUBI:
        return f"subi {arg}: ACC <- ACC - {arg}"
    if op == Opcode.MUL:
        return f"mul {arg}: ACC <- ACC * {addr}"
    if op == Opcode.DIV:
        return f"div {arg}: ACC <- ACC // {addr}"
    if op == Opcode.MOD:
        return f"mod {arg}: ACC <- ACC % {addr}"
    if op == Opcode.CMP:
        return f"cmp {arg}: flags <- ACC - {addr}"
    if op == Opcode.CMPI:
        return f"cmpi {arg}: flags <- ACC - {arg}"
    if op == Opcode.NEG:
        return "neg: ACC <- -ACC"

    if op == Opcode.JMP:
        return f"jmp {arg}: PC <- {arg}"
    if op == Opcode.BEQ:
        return f"beq {arg}: if Z then PC <- {arg}"
    if op == Opcode.BNE:
        return f"bne {arg}: if not Z then PC <- {arg}"
    if op == Opcode.BLT:
        return f"blt {arg}: if N then PC <- {arg}"
    if op == Opcode.BGT:
        return f"bgt {arg}: if not N and not Z then PC <- {arg}"
    if op == Opcode.BLE:
        return f"ble {arg}: if N or Z then PC <- {arg}"
    if op == Opcode.BGE:
        return f"bge {arg}: if not N or Z then PC <- {arg}"

    if op == Opcode.HLT:
        return "hlt: halt"
    return str(instruction)


def to_signed32(value: int) -> int:
    value &= WORD_MASK
    if value & 0x80000000:
        return value - (1 << 32)
    return value


def make_memory_image(instructions: list[Instruction], data: list[int]) -> list[int]:
    memory = [0] * CODE_BASE
    memory.extend(instruction.encode() for instruction in instructions)
    memory.extend(value & WORD_MASK for value in data)
    return memory


def to_bytes(instructions: list[Instruction], data: list[int]) -> bytes:
    memory = make_memory_image(instructions, data)
    words = [CODE_BASE, len(memory), *memory]
    return b"".join(struct.pack(">I", word & WORD_MASK) for word in words)


def write_binary(path: str | Path, instructions: list[Instruction], data: list[int]) -> None:
    Path(path).write_bytes(to_bytes(instructions, data))


def to_listing(instructions: list[Instruction], data: list[int]) -> str:
    data_base = CODE_BASE + len(instructions)
    lines = [f"# entry {CODE_BASE}", "# code"]
    for offset, instruction in enumerate(instructions):
        address = CODE_BASE + offset
        lines.append(f"{address:04} - {instruction.encode():08X} - {mnemonic(instruction)}")

    lines.append("# data")
    for offset, value in enumerate(data):
        address = data_base + offset
        lines.append(f"{address:04} - {value & WORD_MASK:08X} - {to_signed32(value)}")
    return "\n".join(lines)
