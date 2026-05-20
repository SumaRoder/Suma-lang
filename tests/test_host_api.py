from __future__ import annotations

import suma_lang


def test_public_api_compiles_and_runs_source():
    source = """
pub main(): Int {
    return 42
}
"""
    program = suma_lang.compile_source(source, "<host-api-test>")
    assert suma_lang.run_program(program) == 42
    assert suma_lang.run_source(source, filename="<host-api-test>") == 42


def test_public_api_injects_and_reads_runtime_environment():
    source = """
seed: Int
result: Int

pub main(): Int {
    result = seed + 2
    return result
}
"""
    program = suma_lang.compile_source(source, "<host-api-test>")
    vm = suma_lang.create_vm(program)
    suma_lang.inject_environment(vm, {"seed": 40})

    assert vm.run() == 42
    assert vm.get_global("result") == 42
    assert suma_lang.make_environment(vm)["seed"] == 40
    assert suma_lang.make_environment(vm)["result"] == 42


def test_public_api_creates_vm_with_environment_and_reuses_it_for_source():
    source = """
seed: Int

pub main(): Int {
    return seed + 1
}
"""
    vm = suma_lang.create_vm(environment={"seed": 41})

    assert suma_lang.run_source(source, vm=vm, filename="<host-api-test>") == 42
    assert vm.get_global("seed") == 41

    vm.inject("seed", 99)
    assert suma_lang.run_source(source, vm=vm, filename="<host-api-test>") == 100


def test_public_api_injects_python_callable():
    source = """
host_add: PyObject

pub main(): Int {
    return host_add(40, 2)
}
"""

    assert suma_lang.run_source(source, inject={"host_add": lambda a, b: a + b}) == 42
