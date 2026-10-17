"""Safe arithmetic expression evaluator (AST whitelist, no eval)."""
import ast
import math
import operator

C0 = 299792458.0
CONSTANTS = {"pi": math.pi, "c0": C0}
FUNCTIONS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "exp": math.exp, "log": math.log, "abs": abs, "min": min, "max": max,
}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Pow: operator.pow}
UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class ExprError(ValueError):
    pass


def _parse(expr):
    if isinstance(expr, (int, float)):
        return ast.Expression(ast.Constant(float(expr)))
    try:
        return ast.parse(str(expr).strip(), mode="eval")
    except SyntaxError:
        raise ExprError(f"invalid expression '{expr}'") from None


def _eval(node, env, expr):
    if isinstance(node, ast.Expression):
        return _eval(node.body, env, expr)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
        try:
            return BINOPS[type(node.op)](_eval(node.left, env, expr), _eval(node.right, env, expr))
        except ZeroDivisionError:
            raise ExprError(f"division by zero in '{expr}'") from None
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        return UNARY[type(node.op)](_eval(node.operand, env, expr))
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise ExprError(f"unknown variable '{node.id}' in '{expr}'")
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in FUNCTIONS and not node.keywords):
        args = [_eval(a, env, expr) for a in node.args]
        try:
            return float(FUNCTIONS[node.func.id](*args))
        except (ValueError, TypeError) as e:
            raise ExprError(f"{node.func.id}() failed in '{expr}': {e}") from None
    raise ExprError(f"unsupported syntax in '{expr}'")


def evaluate(expr, env=None):
    value = _eval(_parse(expr), env or {}, expr)
    if isinstance(value, complex) or math.isnan(value) or math.isinf(value):
        raise ExprError(f"'{expr}' does not evaluate to a finite real number")
    return value


def resolve_variables(variables):
    """Evaluate a {name: expr} dict where values may reference each other."""
    values, visiting = {}, []

    def resolve(name):
        if name in values:
            return values[name]
        if name in visiting:
            cycle = visiting[visiting.index(name):] + [name]
            raise ExprError("variable cycle: " + " -> ".join(cycle))
        visiting.append(name)
        tree = _parse(variables[name])
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id in variables:
                resolve(n.id)
        visiting.pop()
        try:
            values[name] = evaluate(variables[name], values)
        except ExprError as e:
            raise ExprError(f"variable '{name}': {e}") from None
        return values[name]

    for name in variables:
        if name in CONSTANTS or name in FUNCTIONS:
            raise ExprError(f"variable '{name}' shadows a built-in")
        resolve(name)
    return values
