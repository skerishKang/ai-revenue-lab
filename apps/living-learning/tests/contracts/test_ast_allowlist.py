"""Blocker F: strict AST allowlist for generated Python code.

Only initial-curriculum constructs are allowed; ``Call`` is restricted to
``print()``. Arbitrary calls, attribute access, imports, lambdas, subscripts,
dunder names, and dangerous builtins are rejected.
"""

from __future__ import annotations

from app.pipeline.code_safety import (
    is_safe_code,
    simulate_print_output,
    validate_code_ast,
    validate_code_output,
)


def test_simple_assignment_and_print_allowed():
    code = 'name = "지민"\nstudy_minutes = 10\nprint(name)\nprint(study_minutes)'
    assert is_safe_code(code)


def test_print_output_simulation_matches():
    code = "x = 10\nprint(x)"
    assert simulate_print_output(code) == "10"
    assert validate_code_output(code, "10")


def test_arbitrary_call_rejected():
    assert not is_safe_code("danger()")
    issues = validate_code_ast("danger()")
    assert any("forbidden_call" in i for i in issues)


def test_attribute_access_rejected():
    assert not is_safe_code("import os\nos.system('ls')")
    assert not is_safe_code("x = obj.attr")


def test_import_rejected():
    assert not is_safe_code("import subprocess")
    assert not is_safe_code("from os import path")


def test_lambda_function_class_rejected():
    assert not is_safe_code("f = lambda x: x")
    assert not is_safe_code("def f():\n    return 1")
    assert not is_safe_code("class C:\n    pass")


def test_subscript_rejected():
    assert not is_safe_code("x = [1,2]\ny = x[0]")


def test_open_eval_exec_rejected():
    assert not is_safe_code("open('f.txt')")
    assert not is_safe_code("eval('1+1')")
    assert not is_safe_code("exec('x=1')")


def test_dunder_name_rejected():
    assert not is_safe_code("__import__('os')")


def test_print_with_kwargs_rejected():
    assert not is_safe_code("print('a', sep='-')")


def test_mismatched_expected_output_rejected():
    # Safe code, but the declared output does not match the simulation.
    assert not validate_code_output("x = 10\nprint(x)", "999")


def test_comparison_and_if_allowed():
    code = "x = 5\nif x > 3:\n    print(x)"
    # If/Compare/Gt are in the allowlist (structurally safe), though not simulated.
    assert validate_code_ast(code) == []
