from dataclasses import dataclass
from enum import IntEnum, unique

from isa import Opcode


@unique
class SelAr(IntEnum):
    PC = 0
    ARG = 1
    DR = 2


@unique
class SelPc(IntEnum):
    INC = 0
    ALU = 1


@unique
class SelAluL(IntEnum):
    ACC = 0
    PC = 1


@unique
class SelAluR(IntEnum):
    DR = 0
    ARG = 1


@unique
class AluControl(IntEnum):
    PASS_LEFT = 0
    PASS_RIGHT = 1
    ADD = 2
    SUB = 3
    MUL = 4
    DIV = 5
    MOD = 6
    NEG = 7


@unique
class CondCode(IntEnum):
    NEXT = 0  # MPC + 1
    ALWAYS = 1  # jmp_addr
    DECODE = 2  # opcode mapper
    EQ = 3  # z = 1 -> jmp_addr, иначе next
    NE = 4  # z = 0 -> jmp_addr, иначе next
    LT = 5  # n = 1 -> jmp_addr, иначе next
    GT = 6  # n = 0 and z = 0 -> jmp_addr, иначе next
    LE = 7  # n = 1 or z = 1 -> jmp_addr, иначе next
    GE = 8  # n = 0 -> jmp_addr, иначе next


@dataclass(frozen=True)
class MicroInstruction:
    acc_l: bool = False
    pc_l: bool = False
    dr_l: bool = False
    ar_l: bool = False
    mem_r: bool = False
    mem_wr: bool = False
    flags_l: bool = False
    halted: bool = False
    sel_pc: SelPc = SelPc.INC
    sel_ar: SelAr = SelAr.PC
    sel_alu_l: SelAluL = SelAluL.ACC
    sel_alu_r: SelAluR = SelAluR.DR
    alu_control: AluControl = AluControl.PASS_LEFT
    cond_code: CondCode = CondCode.NEXT
    jmp_addr: int = 0


MROM_SIZE = 128
MROM = [MicroInstruction() for _ in range(MROM_SIZE)]
MROM_DESC = [""] * MROM_SIZE
MROM_LABEL = [""] * MROM_SIZE


def put(address: int, label: str, desc: str, **signals: object) -> None:
    MROM[address] = MicroInstruction(**signals)
    MROM_DESC[address] = desc
    MROM_LABEL[address] = label


# Instruction fetch
put(0, "FETCH", "DR <- Memory[AR]; PC <- PC + 1", mem_r=True, dr_l=True, pc_l=True)
put(1, "FETCH", "AR <- PC; MPC <- DECODER[DR.opcode]", ar_l=True, sel_ar=SelAr.PC, cond_code=CondCode.DECODE)

# LD: ACC <- Mem[arg]
put(2, "LD", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(3, "LD", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(4, "LD", "ACC <- DR; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_r=SelAluR.DR, alu_control=AluControl.PASS_RIGHT,
    cond_code=CondCode.ALWAYS, jmp_addr=0, )

# LDI: ACC <- arg
put(5, "LDI", "ACC <- DR.arg; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_r=SelAluR.ARG, alu_control=AluControl.PASS_RIGHT,
    cond_code=CondCode.ALWAYS, jmp_addr=0, )

# LD_IND: ACC <- Mem[Mem[arg]]
put(6, "LD_IND", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(7, "LD_IND", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(8, "LD_IND", "AR <- DR", ar_l=True, sel_ar=SelAr.DR)
put(9, "LD_IND", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(10, "LD_IND", "ACC <- DR; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_r=SelAluR.DR, alu_control=AluControl.PASS_RIGHT,
    cond_code=CondCode.ALWAYS, jmp_addr=0, )

# ST: Mem[arg] <- ACC
put(11, "ST", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(12,
    "ST",
    "Memory[AR] <- ACC; AR <- PC; -> FETCH",
    mem_wr=True, ar_l=True, sel_ar=SelAr.PC,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

# ST_IND: Mem[Mem[arg]] <- ACC
put(13, "ST_IND", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(14, "ST_IND", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(15, "ST_IND", "AR <- DR", ar_l=True, sel_ar=SelAr.DR)
put(16, "ST_IND", "Memory[AR] <- ACC; AR <- PC; -> FETCH",
    mem_wr=True, ar_l=True, sel_ar=SelAr.PC,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

# Memory arithmetic
put(17, "ADD", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(18, "ADD", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(19, "ADD", "ACC <- ACC + DR; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.DR, alu_control=AluControl.ADD,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

put(20, "SUB", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(21, "SUB", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(22, "SUB", "ACC <- ACC - DR; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.DR, alu_control=AluControl.SUB,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

put(23, "MUL", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(24, "MUL", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(25, "MUL", "ACC <- ACC * DR; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.DR, alu_control=AluControl.MUL,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

put(26, "DIV", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(27, "DIV", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(28, "DIV", "ACC <- ACC // DR; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.DR, alu_control=AluControl.DIV,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

put(29, "MOD", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(30, "MOD", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(31, "MOD", "ACC <- ACC % DR; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.DR, alu_control=AluControl.MOD,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

put(32, "CMP", "AR <- DR.arg", ar_l=True, sel_ar=SelAr.ARG)
put(33, "CMP", "DR <- Memory[AR]", mem_r=True, dr_l=True)
put(34, "CMP", "flags <- ACC - DR; AR <- PC; -> FETCH",
    ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.DR, alu_control=AluControl.SUB,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

# Immediate arithmetic
put(35, "ADDI", "ACC <- ACC + DR.arg; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.ARG, alu_control=AluControl.ADD,
    cond_code=CondCode.ALWAYS, jmp_addr=0)
put(36, "SUBI", "ACC <- ACC - DR.arg; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.ARG, alu_control=AluControl.SUB,
    cond_code=CondCode.ALWAYS, jmp_addr=0)
put(37, "CMPI", "flags <- ACC - DR.arg; AR <- PC; -> FETCH",
    ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, sel_alu_r=SelAluR.ARG, alu_control=AluControl.SUB,
    cond_code=CondCode.ALWAYS, jmp_addr=0)
put(38, "NEG", "ACC <- -ACC; flags <- ACC; AR <- PC; -> FETCH",
    acc_l=True, ar_l=True, flags_l=True, sel_ar=SelAr.PC,
    sel_alu_l=SelAluL.ACC, alu_control=AluControl.NEG,
    cond_code=CondCode.ALWAYS, jmp_addr=0)

# Control flow
put(39, "JMP", "PC <- DR.arg; AR <- DR.arg; -> FETCH",
    pc_l=True, sel_pc=SelPc.ALU, ar_l=True, sel_ar=SelAr.ARG,
    sel_alu_r=SelAluR.ARG, alu_control=AluControl.PASS_RIGHT,
    cond_code=CondCode.ALWAYS, jmp_addr=0)
put(40, "BEQ", "if last cmp == 0 -> JMP", cond_code=CondCode.EQ, jmp_addr=39)
put(41, "BEQ", "AR <- PC; -> FETCH", ar_l=True, sel_ar=SelAr.PC, cond_code=CondCode.ALWAYS, jmp_addr=0)
put(42, "BNE", "if last cmp != 0 -> JMP", cond_code=CondCode.NE, jmp_addr=39)
put(43, "BNE", "AR <- PC; -> FETCH", ar_l=True, sel_ar=SelAr.PC, cond_code=CondCode.ALWAYS, jmp_addr=0)
put(44, "BLT", "if last cmp < 0 -> JMP", cond_code=CondCode.LT, jmp_addr=39)
put(45, "BLT", "AR <- PC; -> FETCH", ar_l=True, sel_ar=SelAr.PC, cond_code=CondCode.ALWAYS, jmp_addr=0)
put(46, "BGT", "if last cmp > 0 -> JMP", cond_code=CondCode.GT, jmp_addr=39)
put(47, "BGT", "AR <- PC; -> FETCH", ar_l=True, sel_ar=SelAr.PC, cond_code=CondCode.ALWAYS, jmp_addr=0)
put(48, "BLE", "if last cmp <= 0 -> JMP", cond_code=CondCode.LE, jmp_addr=39)
put(49, "BLE", "AR <- PC; -> FETCH", ar_l=True, sel_ar=SelAr.PC, cond_code=CondCode.ALWAYS, jmp_addr=0)
put(50, "BGE", "if last cmp >= 0 -> JMP", cond_code=CondCode.GE, jmp_addr=39)
put(51, "BGE", "AR <- PC; -> FETCH", ar_l=True, sel_ar=SelAr.PC, cond_code=CondCode.ALWAYS, jmp_addr=0)

put(52, "HLT", "HALT", halted=True)

DECODER = [0] * 256
DECODER[Opcode.LD] = 2
DECODER[Opcode.LDI] = 5
DECODER[Opcode.LD_IND] = 6
DECODER[Opcode.ST] = 11
DECODER[Opcode.ST_IND] = 13
DECODER[Opcode.ADD] = 17
DECODER[Opcode.SUB] = 20
DECODER[Opcode.MUL] = 23
DECODER[Opcode.DIV] = 26
DECODER[Opcode.MOD] = 29
DECODER[Opcode.CMP] = 32
DECODER[Opcode.ADDI] = 35
DECODER[Opcode.SUBI] = 36
DECODER[Opcode.CMPI] = 37
DECODER[Opcode.NEG] = 38
DECODER[Opcode.JMP] = 39
DECODER[Opcode.BEQ] = 40
DECODER[Opcode.BNE] = 42
DECODER[Opcode.BLT] = 44
DECODER[Opcode.BGT] = 46
DECODER[Opcode.BLE] = 48
DECODER[Opcode.BGE] = 50
DECODER[Opcode.HLT] = 52
