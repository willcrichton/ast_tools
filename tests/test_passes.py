import os
import functools
import inspect

from ast_tools.passes import begin_rewrite, end_rewrite, debug
from ast_tools.stack import SymbolTable


def test_begin_end():
    def wrapper(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapped

    @wrapper
    @end_rewrite()
    @begin_rewrite()
    @wrapper
    def foo():
        pass

    assert inspect.getsource(foo) == '''\
@wrapper
@wrapper
def foo():
    pass
'''


def test_debug(capsys):

    @end_rewrite()
    @debug(dump_source_filename=True, dump_source_lines=True)
    @begin_rewrite(debug=True)
    def foo():
        print("bar")
    assert capsys.readouterr().out == f"""\
BEGIN SOURCE_FILENAME
{os.path.abspath(__file__)}
END SOURCE_FILENAME

BEGIN SOURCE_LINES
33:    @end_rewrite()
34:    @debug(dump_source_filename=True, dump_source_lines=True)
35:    @begin_rewrite(debug=True)
36:    def foo():
37:        print("bar")
END SOURCE_LINES

"""


def test_debug_error():

    try:
        @end_rewrite
        @debug(dump_source_filename=True)
        @begin_rewrite()
        def foo():
            print("bar")
    except Exception as e:
        assert str(e) == "Cannot dump source filename without @begin_rewrite(debug=True)"

    try:
        @end_rewrite
        @debug(dump_source_lines=True)
        @begin_rewrite()
        def foo():
            print("bar")
    except Exception as e:
        assert str(e) == "Cannot dump source lines without @begin_rewrite(debug=True)"


def test_custom_env():
    @end_rewrite()
    @begin_rewrite(env=SymbolTable({'x': 1}, globals=globals()))
    def f():
        return x

    assert f() == 1
