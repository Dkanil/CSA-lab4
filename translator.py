import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path

from isa import CODE_BASE, IN_PORT, OUT_PORT, Instruction, Opcode, to_listing, write_binary

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
INTEGER_RE = re.compile(r"\d+\Z")
COND_RE = re.compile(r"(.+?)\s*(==|!=|<=|>=|<|>)\s*(.+)\Z")
DEFAULT_PSTR_CAPACITY = 80


@dataclass
class Statement:
    kind: str
    line: int
    name: str = ""
    type_name: str = ""
    expr: str = ""
    condition: str = ""
    value: str = ""


@dataclass
class _CodeItem:
    opcode: Opcode
    operand: int = 0
    operand_kind: str = "raw"


@dataclass
class _Operand:
    value: int
    kind: str = "raw"


class Translator:
    def __init__(self) -> None:
        self.code: list[_CodeItem] = []
        self.data: list[int] = []
        self.symbols: dict[str, int] = {}
        self.types: dict[str, str] = {}
        self.pstr_capacity: dict[str, int] = {}
        self.blocks: list[tuple] = []
        self.ast: list[Statement] = []
        self.temp_index = 0
        self.free_expr_temps: list[int] = []

    def compile(self, source: str) -> tuple[list[Instruction], list[int], str]:
        self.ast = self.parse(source)
        for statement in self.ast:
            self.emit_statement(statement)
        if self.blocks:
            raise SyntaxError("unclosed block")
        self.emit(Opcode.HLT)
        return self.resolve_code(), self.data, self.ast_text()

    def parse(self, source: str) -> list[Statement]:
        statements: list[Statement] = []
        depth = 0
        for line_no, raw_line in enumerate(source.splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            statement = self.parse_line(line_no, line)
            if statement.kind in {"if", "while"}:
                depth += 1
            elif statement.kind == "else":
                if depth <= 0:
                    raise SyntaxError(f"line {line_no}: else without block")
            elif statement.kind == "end":
                depth -= 1
                if depth < 0:
                    raise SyntaxError(f"line {line_no}: end without block")
            statements.append(statement)
        if depth != 0:
            raise SyntaxError("unclosed block")
        return statements

    def parse_line(self, line_no: int, line: str) -> Statement:
        if line.startswith("var "):
            parts = line.split()
            if len(parts) != 3 or parts[1] not in {"num", "char", "pstr"}:
                raise SyntaxError(f"line {line_no}: expected 'var <num|char|pstr> <id>'")
            self.declare_var(parts[2], parts[1])
            return Statement("var", line_no, name=parts[2], type_name=parts[1])

        if line.startswith("pstr "):
            rest = line[5:].strip()
            name, _, raw_string = rest.partition(" ")
            raw_string = raw_string.strip()
            if not name or not raw_string:
                raise SyntaxError(f"line {line_no}: expected 'pstr <id> \"text\"'")
            try:
                text = ast.literal_eval(raw_string)
            except (SyntaxError, ValueError) as exc:
                raise SyntaxError(f"line {line_no}: bad string literal") from exc
            if not isinstance(text, str):
                raise SyntaxError(f"line {line_no}: pstr literal must be a string")
            self.declare_pstr_literal(name, text)
            return Statement("pstr", line_no, name=name, value=text)

        if line.startswith("set "):
            name, sep, expr = line[4:].partition("=")
            if sep != "=":
                raise SyntaxError(f"line {line_no}: expected 'set <id> = <expr>'")
            name = name.strip()
            expr = expr.strip()
            self.require_type(name, {"num", "char"}, line_no)
            self.validate_expr(expr, line_no)
            return Statement("set", line_no, name=name, expr=expr)

        if line.startswith("input(") and line.endswith(")"):
            name = line[6:-1].strip()
            self.require_type(name, {"num", "char", "pstr"}, line_no)
            return Statement("input", line_no, name=name)

        if line.startswith("print(") and line.endswith(")"):
            expr = line[6:-1].strip()
            if expr not in self.types:
                self.validate_expr(expr, line_no)
            return Statement("print", line_no, expr=expr)

        if line.startswith("if ") and line.endswith(":"):
            condition = line[3:-1].strip()
            self.validate_condition(condition, line_no)
            return Statement("if", line_no, condition=condition)

        if line.startswith("while ") and line.endswith(":"):
            condition = line[6:-1].strip()
            self.validate_condition(condition, line_no)
            return Statement("while", line_no, condition=condition)

        if line == "else:":
            return Statement("else", line_no)
        if line == "end":
            return Statement("end", line_no)

        raise SyntaxError(f"line {line_no}: unknown statement '{line}'")

    def declare_var(self, name: str, type_name: str) -> None:
        self.validate_identifier(name)
        if name in self.types:
            raise SyntaxError(f"name already declared: {name}")
        self.types[name] = type_name
        self.symbols[name] = len(self.data)
        if type_name == "pstr":
            self.pstr_capacity[name] = DEFAULT_PSTR_CAPACITY
            self.data.extend([0] * (DEFAULT_PSTR_CAPACITY + 1))
        else:
            self.data.append(0)

    def declare_pstr_literal(self, name: str, text: str) -> None:
        self.validate_identifier(name)
        if name in self.types:
            raise SyntaxError(f"name already declared: {name}")
        if any(ord(char) > 0x7F for char in text):
            raise SyntaxError("only ASCII strings are supported")
        self.types[name] = "pstr"
        self.pstr_capacity[name] = len(text)
        self.symbols[name] = len(self.data)
        self.data.append(len(text))
        self.data.extend(ord(char) for char in text)

    def validate_identifier(self, name: str) -> None:
        if not IDENT_RE.fullmatch(name):
            raise SyntaxError(f"bad identifier: {name}")

    def require_type(self, name: str, allowed: set[str], line_no: int) -> None:
        if self.types.get(name) not in allowed:
            raise SyntaxError(f"line {line_no}: unexpected or undeclared identifier '{name}'")

    def validate_expr(self, expr: str, line_no: int) -> None:
        try:
            node = ast.parse(expr, mode="eval").body
        except SyntaxError as exc:
            raise SyntaxError(f"line {line_no}: bad expression '{expr}'") from exc
        self.validate_expr_node(node, expr, line_no)

    def validate_expr_node(self, node: ast.AST, source: str, line_no: int) -> None:
        # <integer>
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            segment = ast.get_source_segment(source, node)
            if segment is None or not INTEGER_RE.fullmatch(segment):
                raise SyntaxError(f"line {line_no}: integer literal must contain only digits")
            return
        # <id>
        if isinstance(node, ast.Name):
            self.require_type(node.id, {"num", "char"}, line_no)
            return
        # - <atom>
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            self.validate_expr_node(node.operand, source, line_no)
            return
        # <expr>
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
            self.validate_expr_node(node.left, source, line_no)
            self.validate_expr_node(node.right, source, line_no)
            return
        raise SyntaxError(f"line {line_no}: unsupported expression node {ast.dump(node)}")

    def validate_condition(self, condition: str, line_no: int) -> None:
        match = COND_RE.fullmatch(condition)
        if not match:
            raise SyntaxError(f"line {line_no}: bad condition '{condition}'")
        self.validate_expr(match.group(1).strip(), line_no)
        self.validate_expr(match.group(3).strip(), line_no)

    @staticmethod
    def raw(value: int) -> _Operand:
        return _Operand(value, "raw")

    @staticmethod
    def data_ref(offset: int) -> _Operand:
        return _Operand(offset, "data")

    @staticmethod
    def code_ref(offset: int) -> _Operand:
        return _Operand(offset, "code")

    def emit(self, opcode: Opcode, operand: _Operand | int = 0) -> int:
        if isinstance(operand, _Operand):
            item = _CodeItem(opcode, operand.value, operand.kind)
        else:
            item = _CodeItem(opcode, operand, "raw")
        self.code.append(item)
        return len(self.code) - 1

    def patch(self, pos: int, target: int) -> None:
        self.code[pos].operand = target

    def resolve_code(self) -> list[Instruction]:
        data_base = CODE_BASE + len(self.code)
        instructions: list[Instruction] = []
        for item in self.code:
            operand = item.operand
            if item.operand_kind == "data":
                operand += data_base
            elif item.operand_kind == "code":
                operand += CODE_BASE
            instructions.append(Instruction(item.opcode, operand))
        return instructions

    def alloc_temp(self, name: str) -> int:
        actual = f"__{name}_{self.temp_index}"
        self.temp_index += 1
        self.symbols[actual] = len(self.data)
        self.types[actual] = "num"
        self.data.append(0)
        return self.symbols[actual]

    def alloc_expr_temp(self) -> int:
        if self.free_expr_temps:
            return self.free_expr_temps.pop()
        return self.alloc_temp("expr")

    def free_expr_temp(self, cell: int) -> None:
        self.free_expr_temps.append(cell)

    def emit_statement(self, statement: Statement) -> None:
        if statement.kind in {"var", "pstr"}:
            return
        if statement.kind == "set":
            self.emit_expr(statement.expr)
            self.emit(Opcode.ST, self.data_ref(self.symbols[statement.name]))
            return
        if statement.kind == "input":
            self.emit_input(statement.name)
            return
        if statement.kind == "print":
            self.emit_print(statement.expr)
            return
        if statement.kind == "if":
            patch_site = self.emit_false_jump(statement.condition)
            self.blocks.append(("if", patch_site))
            return
        if statement.kind == "else":
            kind, patch_site = self.blocks.pop()
            if kind != "if":
                raise SyntaxError(f"line {statement.line}: else after non-if block")
            end_jump = self.emit(Opcode.JMP, self.code_ref(0))
            self.patch(patch_site, len(self.code))
            self.blocks.append(("else", end_jump))
            return
        if statement.kind == "while":
            start = len(self.code)
            patch_site = self.emit_false_jump(statement.condition)
            self.blocks.append(("while", start, patch_site))
            return
        if statement.kind == "end":
            block = self.blocks.pop()
            if block[0] == "while":
                _, start, patch_site = block
                self.emit(Opcode.JMP, self.code_ref(start))
                self.patch(patch_site, len(self.code))
            else:
                self.patch(block[1], len(self.code))
            return
        raise AssertionError(f"unknown statement kind: {statement.kind}")

    def emit_expr(self, expr: str) -> None:
        self.emit_expr_node(ast.parse(expr, mode="eval").body)

    def emit_expr_node(self, node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            self.emit(Opcode.LDI, self.raw(int(node.value)))
            return
        if isinstance(node, ast.Name):
            self.emit(Opcode.LD, self.data_ref(self.symbols[node.id]))
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            self.emit_expr_node(node.operand)
            self.emit(Opcode.NEG)
            return
        if isinstance(node, ast.BinOp):
            right_imm = self.immediate_int(node.right)
            if right_imm is not None and isinstance(node.op, (ast.Add, ast.Sub)):
                self.emit_expr_node(node.left)
                opcode = Opcode.ADDI if isinstance(node.op, ast.Add) else Opcode.SUBI
                self.emit(opcode, self.raw(right_imm))
                return
            self.emit_expr_node(node.left)
            left = self.alloc_expr_temp()
            self.emit(Opcode.ST, self.data_ref(left))
            self.emit_expr_node(node.right)
            right = self.alloc_expr_temp()
            self.emit(Opcode.ST, self.data_ref(right))
            self.emit(Opcode.LD, self.data_ref(left))
            opcodes = {
                ast.Add: Opcode.ADD,
                ast.Sub: Opcode.SUB,
                ast.Mult: Opcode.MUL,
                ast.FloorDiv: Opcode.DIV,
                ast.Mod: Opcode.MOD,
            }
            self.emit(opcodes[type(node.op)], self.data_ref(right))
            self.free_expr_temp(right)
            self.free_expr_temp(left)
            return
        raise AssertionError(f"unsupported expression node: {ast.dump(node)}")

    def emit_false_jump(self, condition: str) -> int:
        match = COND_RE.fullmatch(condition)
        if not match:
            raise AssertionError(f"bad condition: {condition}")
        left, op, right = (part.strip() for part in match.groups())
        self.emit_expr(left)
        right_node = ast.parse(right, mode="eval").body
        right_imm = self.immediate_int(right_node)
        if right_imm is not None:
            self.emit(Opcode.CMPI, self.raw(right_imm))
        else:
            left_cell = self.alloc_expr_temp()
            self.emit(Opcode.ST, self.data_ref(left_cell))
            self.emit_expr(right)
            right_cell = self.alloc_expr_temp()
            self.emit(Opcode.ST, self.data_ref(right_cell))
            self.emit(Opcode.LD, self.data_ref(left_cell))
            self.emit(Opcode.CMP, self.data_ref(right_cell))
            self.free_expr_temp(right_cell)
            self.free_expr_temp(left_cell)

        if op == "==":
            return self.emit(Opcode.BNE, self.code_ref(0))
        if op == "!=":
            return self.emit(Opcode.BEQ, self.code_ref(0))
        if op == "<":
            return self.emit(Opcode.BGE, self.code_ref(0))
        if op == "<=":
            return self.emit(Opcode.BGT, self.code_ref(0))
        if op == ">":
            return self.emit(Opcode.BLE, self.code_ref(0))
        if op == ">=":
            return self.emit(Opcode.BLT, self.code_ref(0))
        raise AssertionError(f"unsupported comparison: {op}")

    def emit_input(self, name: str) -> None:
        if self.types[name] in {"num", "char"}:
            self.emit(Opcode.LD, self.raw(IN_PORT))
            self.emit(Opcode.ST, self.data_ref(self.symbols[name]))
            return

        ptr = self.alloc_temp("input_ptr")
        left = self.alloc_temp("input_left")
        length = self.alloc_temp("input_len")
        char = self.alloc_temp("input_char")
        capacity = self.pstr_capacity[name]
        self.emit_data_address(self.symbols[name] + 1)
        self.emit(Opcode.ST, self.data_ref(ptr))
        self.emit(Opcode.LD, self.raw(IN_PORT))
        self.emit(Opcode.ST, self.data_ref(left))
        self.emit(Opcode.LDI, self.raw(0))
        self.emit(Opcode.ST, self.data_ref(length))

        loop = len(self.code)
        self.emit(Opcode.LD, self.data_ref(left))
        self.emit(Opcode.CMPI, self.raw(0))
        done_jump = self.emit(Opcode.BEQ, self.code_ref(0))
        self.emit(Opcode.LD, self.raw(IN_PORT))
        self.emit(Opcode.ST, self.data_ref(char))
        self.emit(Opcode.LD, self.data_ref(left))
        self.emit(Opcode.SUBI, self.raw(1))
        self.emit(Opcode.ST, self.data_ref(left))
        self.emit(Opcode.LD, self.data_ref(length))
        self.emit(Opcode.CMPI, self.raw(capacity))
        full_jump = self.emit(Opcode.BEQ, self.code_ref(0))
        self.emit(Opcode.LD, self.data_ref(char))
        self.emit(Opcode.ST_IND, self.data_ref(ptr))
        self.emit(Opcode.LD, self.data_ref(ptr))
        self.emit(Opcode.ADDI, self.raw(1))
        self.emit(Opcode.ST, self.data_ref(ptr))
        self.emit(Opcode.LD, self.data_ref(length))
        self.emit(Opcode.ADDI, self.raw(1))
        self.emit(Opcode.ST, self.data_ref(length))
        self.patch(full_jump, len(self.code))
        self.emit(Opcode.JMP, self.code_ref(loop))
        self.patch(done_jump, len(self.code))
        self.emit(Opcode.LD, self.data_ref(length))
        self.emit(Opcode.ST, self.data_ref(self.symbols[name]))

    def emit_print(self, expr: str) -> None:
        if expr in self.types and self.types[expr] == "pstr":
            self.emit_print_pstr(expr)
        else:
            self.emit_expr(expr)
            self.emit(Opcode.ST, self.raw(OUT_PORT))

    def emit_print_pstr(self, name: str) -> None:
        ptr = self.alloc_temp("print_ptr")
        left = self.alloc_temp("print_left")
        self.emit_data_address(self.symbols[name] + 1)
        self.emit(Opcode.ST, self.data_ref(ptr))
        self.emit(Opcode.LD, self.data_ref(self.symbols[name]))
        self.emit(Opcode.ST, self.data_ref(left))
        loop = len(self.code)
        self.emit(Opcode.LD, self.data_ref(left))
        self.emit(Opcode.CMPI, self.raw(0))
        done_jump = self.emit(Opcode.BEQ, self.code_ref(0))
        self.emit(Opcode.LD_IND, self.data_ref(ptr))
        self.emit(Opcode.ST, self.raw(OUT_PORT))
        self.emit(Opcode.LD, self.data_ref(ptr))
        self.emit(Opcode.ADDI, self.raw(1))
        self.emit(Opcode.ST, self.data_ref(ptr))
        self.emit(Opcode.LD, self.data_ref(left))
        self.emit(Opcode.SUBI, self.raw(1))
        self.emit(Opcode.ST, self.data_ref(left))
        self.emit(Opcode.JMP, self.code_ref(loop))
        self.patch(done_jump, len(self.code))

    def emit_data_address(self, offset: int) -> None:
        self.emit(Opcode.LDI, self.data_ref(offset))

    @staticmethod
    def immediate_int(node: ast.AST) -> int | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            value = int(node.value)
            if -(1 << 23) <= value < (1 << 23):
                return value
        return None

    def ast_text(self) -> str:
        lines = []
        for statement in self.ast:
            attrs = []
            for field in ("line", "name", "type_name", "expr", "condition", "value"):
                value = getattr(statement, field)
                if value:
                    attrs.append(f"{field}={value!r}")
            lines.append(f"{statement.kind}(" + ", ".join(attrs) + ")")
            if statement.expr:
                self.collect_expr_ast(ast.parse(statement.expr, mode="eval").body, "  expr: ", "  ", lines)
            if statement.condition:
                match = COND_RE.fullmatch(statement.condition)
                if match:
                    left, op, right = (part.strip() for part in match.groups())
                    lines.append(f"  condition_op: {op!r}")
                    self.collect_expr_ast(ast.parse(left, mode="eval").body, "  left: ", "  ", lines)
                    self.collect_expr_ast(ast.parse(right, mode="eval").body, "  right: ", "  ", lines)
        return "\n".join(lines)

    def collect_expr_ast(self, node: ast.AST, prefix: str, child_prefix: str, lines: list[str]) -> None:
        if isinstance(node, ast.Constant):
            lines.append(f"{prefix}Literal(value={node.value!r})")
            return
        if isinstance(node, ast.Name):
            lines.append(f"{prefix}Identifier(name={node.id!r})")
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            lines.append(f"{prefix}UnaryExpr(op='-')")
            self.collect_expr_ast(node.operand, f"{child_prefix}operand: ", f"{child_prefix}  ", lines)
            return
        if isinstance(node, ast.BinOp):
            op = {
                ast.Add: "+",
                ast.Sub: "-",
                ast.Mult: "*",
                ast.FloorDiv: "//",
                ast.Mod: "%",
            }[type(node.op)]
            lines.append(f"{prefix}BinaryExpr(op={op!r})")
            self.collect_expr_ast(node.left, f"{child_prefix}left: ", f"{child_prefix}  ", lines)
            self.collect_expr_ast(node.right, f"{child_prefix}right: ", f"{child_prefix}  ", lines)
            return
        raise AssertionError(f"Unexpected ast node: {node}")


def translate(source: str) -> tuple[list[Instruction], list[int], str]:
    return Translator().compile(source)


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate lab4 source code to binary machine code")
    parser.add_argument("source", help="source file")
    parser.add_argument("target", help="target binary file")
    args = parser.parse_args()

    source_path = Path(args.source)
    target_path = Path(args.target)
    code, data, ast_dump = translate(source_path.read_text(encoding="utf-8"))

    target_path.parent.mkdir(parents=True, exist_ok=True)
    write_binary(target_path, code, data)

    listing_path = target_path.with_suffix(target_path.suffix + ".lst")
    ast_path = target_path.with_suffix(target_path.suffix + ".ast")
    listing_path.write_text(to_listing(code, data), encoding="utf-8")
    ast_path.write_text(ast_dump, encoding="utf-8")
    print(f"Строк в исходном коде: {len(source_path.read_text(encoding='utf-8').splitlines())}")
    print(f"Строк в машинном коде: {len(code)}")
    print(f"Машинных слов памяти необходимого для выполнения программы: {len(data)}")
    print("\nЧудо скомпилировалось в следующие файлы:")
    print(f"Бинарник: {target_path}")
    print(f"Машинный код: {listing_path}")
    print(f"AST дерево: {ast_path}")


if __name__ == "__main__":
    main()
