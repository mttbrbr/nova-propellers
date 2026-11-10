"""A small, safe arithmetic language for block expressions and constraints.

Only numeric literals, named quantities, arithmetic, comparisons, conditional
expressions and a whitelist of math functions are accepted; attribute access,
subscripts, lambdas and any other Python construct are rejected at parse time.
"""
import ast
import math

FUNCTIONS = {
    'sqrt': math.sqrt, 'sin': math.sin, 'cos': math.cos, 'tan': math.tan, 'asin': math.asin,
    'acos': math.acos, 'atan': math.atan, 'atan2': math.atan2, 'exp': math.exp, 'log': math.log,
    'log10': math.log10, 'abs': abs, 'min': min, 'max': max, 'radians': math.radians,
    'degrees': math.degrees, 'floor': math.floor, 'ceil': math.ceil, 'hypot': math.hypot,
}
CONSTANTS = {'pi': math.pi, 'e': math.e, 'g': 9.80665}
BINARY = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
          ast.Div: lambda a, b: a / b, ast.Mod: lambda a, b: a % b, ast.Pow: None}
COMPARE = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b,
           ast.GtE: lambda a, b: a >= b, ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}
MAX_LENGTH = 400


class ExpressionError(ValueError):
    pass


def parse(text):
    if not isinstance(text, str) or not text.strip():
        raise ExpressionError('Expression is empty')
    if len(text) > MAX_LENGTH:
        raise ExpressionError(f'Expression longer than {MAX_LENGTH} characters')
    try:
        tree = ast.parse(text.strip(), mode='eval')
    except SyntaxError as exc:
        raise ExpressionError(f'Invalid expression: {exc.msg}') from exc
    for node in ast.walk(tree):
        allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.Call,
                   ast.Compare, ast.IfExp, ast.BoolOp, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
                   *BINARY, *COMPARE)
        if not isinstance(node, allowed):
            raise ExpressionError(f'Unsupported syntax: {type(node).__name__}')
        if isinstance(node, ast.Constant) and (isinstance(node.value, bool) or not isinstance(node.value, (int, float))):
            raise ExpressionError('Only numeric constants are allowed')
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or node.keywords:
                raise ExpressionError('Unknown function')
    return tree


def names(text):
    tree = parse(text)
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - called - set(CONSTANTS))


def evaluate(text, variables):
    tree = parse(text)

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in variables:
                value = variables[node.id]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ExpressionError(f'{node.id} is not a number')
                return float(value)
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise ExpressionError(f'Unknown quantity {node.id!r}')
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else (float(not value) if isinstance(node.op, ast.Not) else value)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow):
                if abs(right) > 64 or abs(left) > 1e100:
                    raise ExpressionError('Exponent out of range')
                return left ** right
            if isinstance(node.op, (ast.Div, ast.Mod)) and right == 0:
                raise ExpressionError('Division by zero')
            return BINARY[type(node.op)](left, right)
        if isinstance(node, ast.Compare):
            left = visit(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = visit(comparator)
                if not COMPARE[type(op)](left, right):
                    return 0.0
                left = right
            return 1.0
        if isinstance(node, ast.BoolOp):
            values = [visit(v) for v in node.values]
            return float(all(values) if isinstance(node.op, ast.And) else any(values))
        if isinstance(node, ast.IfExp):
            return visit(node.body) if visit(node.test) else visit(node.orelse)
        if isinstance(node, ast.Call):
            return float(FUNCTIONS[node.func.id](*[visit(a) for a in node.args]))
        raise ExpressionError('Unsupported syntax')

    try:
        result = visit(tree)
    except (OverflowError, ValueError, TypeError, ZeroDivisionError) as exc:
        if isinstance(exc, ExpressionError):
            raise
        raise ExpressionError(f'Cannot evaluate {text!r}: {exc}') from exc
    if not math.isfinite(result):
        raise ExpressionError(f'{text!r} is not finite')
    return result
