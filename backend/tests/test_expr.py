import math

import pytest

from backend.expr import ExprError, evaluate, resolve_variables


def test_arithmetic_and_functions():
    assert evaluate("2+3*4") == 14
    assert evaluate("(2+3)*4") == 20
    assert evaluate("2**10") == 1024
    assert evaluate("-x/2", {"x": 4}) == -2
    assert evaluate("sqrt(16) + cos(0)") == 5
    assert evaluate("c0/2.4e9") == pytest.approx(0.1249135)
    assert evaluate("pi") == math.pi
    assert evaluate(3.5) == 3.5


@pytest.mark.parametrize("bad", ["__import__('os')", "x.y", "[1,2]", "1 if 1 else 2", "a<b",
                                 "open('f')", "lambda: 1", "2 +"])
def test_rejects_unsafe_or_invalid(bad):
    with pytest.raises(ExprError):
        evaluate(bad, {"x": 1, "a": 1, "b": 2})


def test_errors_are_specific():
    with pytest.raises(ExprError, match="unknown variable 'hh'"):
        evaluate("hh*2")
    with pytest.raises(ExprError, match="division by zero"):
        evaluate("1/0")
    with pytest.raises(ExprError, match="finite real"):
        evaluate("(-1)**0.5")


def test_variables_reference_each_other_in_any_order():
    v = resolve_variables({"L": "0.48*lam", "lam": "c0/f0", "f0": "1e9"})
    assert v["L"] == pytest.approx(0.48 * 299792458 / 1e9)


def test_cycle_is_reported_with_path():
    with pytest.raises(ExprError, match="variable cycle: a -> b -> c -> a"):
        resolve_variables({"a": "b+1", "b": "c", "c": "a*2"})
    with pytest.raises(ExprError, match="variable cycle: x -> x"):
        resolve_variables({"x": "x+1"})


def test_variable_error_names_the_variable():
    with pytest.raises(ExprError, match="variable 'w': unknown variable 'q'"):
        resolve_variables({"w": "q*2"})
    with pytest.raises(ExprError, match="shadows"):
        resolve_variables({"pi": "3"})
