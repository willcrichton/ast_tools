import ast
import inspect

import pytest

from ast_tools.common import exec_def_in_file
from ast_tools.passes import begin_rewrite, end_rewrite, ssa, debug
from ast_tools.stack import SymbolTable

basic_template = '''\
def basic(x):
    if x:
        {} 0
    else:
        {} 2
    {}
'''

template_options = ['r =', 'return']

def _do_ssa(func, **kwargs):
    for dec in (
            begin_rewrite(),
            debug(**kwargs),
            ssa(),
            debug(**kwargs),
            end_rewrite()):
        func = dec(func)
    return func

@pytest.mark.parametrize("a", template_options)
@pytest.mark.parametrize("b", template_options)
def test_basic_if(a, b):
    if a == b == 'return':
        final = ''
    else:
        final = 'return r'

    src = basic_template.format(a, b, final)
    tree = ast.parse(src).body[0]
    env = SymbolTable({}, {})
    basic = exec_def_in_file(tree, env)
    ssa_basic = _do_ssa(basic, dump_src=True)

    for x in (False, True):
        assert basic(x) == ssa_basic(x)


nested_template = '''\
def nested(x, y):
    if x:
        if y:
            {} 0
        else:
            {} 1
    else:
        if y:
            {} 2
        else:
            {} 3
    {}
'''

@pytest.mark.parametrize("a", template_options)
@pytest.mark.parametrize("b", template_options)
@pytest.mark.parametrize("c", template_options)
@pytest.mark.parametrize("d", template_options)
def test_nested(a,b,c,d):
    if a == b == c == d == 'return':
        final = ''
    else:
        final = 'return r'

    src = nested_template.format(a, b, c, d, final)
    tree = ast.parse(src).body[0]
    env = SymbolTable({}, {})
    nested = exec_def_in_file(tree, env)
    ssa_nested = _do_ssa(nested, dump_src=True)

    for x in (False, True):
        for y in (False, True):
            assert nested(x, y) == ssa_nested(x, y)

imbalanced_template = '''\
def imbalanced(x, y):
    {} -1
    if x:
        {} -2
        if y:
            {} 0
    else:
        {} 1
    return r
'''

init_template_options = ['r = ', '0']
@pytest.mark.parametrize("a", init_template_options)
@pytest.mark.parametrize("b", init_template_options)
@pytest.mark.parametrize("c", template_options)
@pytest.mark.parametrize("d", template_options)
def test_imbalanced(a, b, c, d):
    src = imbalanced_template.format(a, b, c, d)
    tree = ast.parse(src).body[0]
    env = SymbolTable({}, {})
    imbalanced = exec_def_in_file(tree, env)
    can_name_error = False
    for x in (False, True):
        for y in (False, True):
            try:
                imbalanced(x, y)
            except NameError:
                can_name_error = True
                break

    if can_name_error:
        with pytest.raises(SyntaxError):
            imbalanced_ssa = _do_ssa(imbalanced, dump_src=True)
    else:
        imbalanced_ssa = _do_ssa(imbalanced, dump_src=True)
        for x in (False, True):
            for y in (False, True):
                assert imbalanced(x, y) == imbalanced_ssa(x, y)


def test_reassign_arg():
    def bar(x):
        return x

    @end_rewrite()
    @ssa()
    @begin_rewrite()
    def foo(a, b):
        if b:
            a = len(a)
        return a
    assert inspect.getsource(foo) == """\
def foo(a, b):
    a0 = len(a)
    a1 = a0 if b else a
    __return_value0 = a1
    return __return_value0
"""


def test_double_nested_function_call():
    def bar(x):
        return x

    def baz(x):
        return x + 1

    @end_rewrite()
    @ssa()
    @begin_rewrite()
    def foo(a, b, c):
        if b:
            a = bar(a)
        else:
            a = bar(a)
        if c:
            b = bar(b)
        else:
            b = bar(b)
        return a, b
    print(inspect.getsource(foo))
    assert inspect.getsource(foo) == """\
def foo(a, b, c):
    a0 = bar(a)
    a1 = bar(a)
    a2 = a0 if b else a1
    b0 = bar(b)
    b1 = bar(b)
    b2 = b0 if c else b1
    __return_value0 = a2, b2
    return __return_value0
"""
