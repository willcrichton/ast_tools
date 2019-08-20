import ast
from collections import ChainMap, Counter
import itertools
import warnings
import weakref
import typing as tp

import astor

from . import Pass
from . import PASS_ARGS_T
from ast_tools.common import gen_free_prefix, is_free_name
from ast_tools.stack import SymbolTable
from ast_tools.transformers import Renamer

__ALL__ = ['ssa']

class SSATransformer(ast.NodeTransformer):
    def __init__(self, env, return_value_prefx):
        self.env = env
        self.name_idx = Counter()
        self.name_table = ChainMap()
        self.root = None
        self.cond_stack = []
        self.return_value_prefx = return_value_prefx
        self.returns = []


    def _make_name(self, name):
        new_name = name + str(self.name_idx[name])
        self.name_idx[name] += 1
        while not is_free_name(self.root, self.env, new_name):
            new_name = name + str(self.name_idx[name])
            self.name_idx[name] += 1

        self.name_table[name] = new_name
        return new_name


    def _make_return(self):
        p = self.return_value_prefx
        name = p + str(self.name_idx[p])
        self.name_idx[p] += 1
        return name


    def visit(self, node: ast.AST) -> ast.AST:
        # basically want to able to visit a top level function
        # but don't want to generally recurse into them
        if self.root is None:
            self.root = node
            if isinstance(node, ast.FunctionDef):
                for arg in node.args.args:
                    arg_name = arg.arg
                    self.name_table[arg_name] = arg_name
            else:
                raise TypeError('SSATransformer must be rooted at a function')
            _prove_names_defined(self.env, self.name_table.keys(), node.body)
            if not _always_returns(node.body):
                raise SyntaxError(f'Cannot prove {node.id} returns')
            return super().generic_visit(node)
        else:
            return super().visit(node)


    def visit_If(self, node: ast.If) -> tp.List[ast.stmt]:
        test = self.visit(node.test)
        nt = self.name_table
        suite = []

        # determine if either branch always returns
        t_returns = _always_returns(node.body)
        f_returns = _always_returns(node.orelse)

        self.name_table = t_nt = nt.new_child()
        self.cond_stack.append(test)

        # gather nodes from the body
        for child in node.body:
            child = self.visit(child)
            if child is None:
                continue
            elif isinstance(child, tp.Sequence):
                suite.extend(child)
            else:
                suite.append(child)

        self.cond_stack.pop()
        self.cond_stack.append(ast.UnaryOp(ast.Not(), test))
        self.name_table = f_nt = nt.new_child()

        # gather nodes from the orelse
        for child in node.orelse:
            child = self.visit(child)
            if child is None:
                continue
            elif isinstance(child, tp.Sequence):
                suite.extend(child)
            else:
                suite.append(child)

        self.cond_stack.pop()
        self.name_table = nt

        # Note by first checking for fall through conditions
        # then muxing construction of unnecessary muxes is avoided.
        # However it does obscure program logic somewhat as it will
        # appear as if old values of names are used.
        # e.g.:
        #   if cond:
        #       var = 1
        #   else:
        #       var = 2
        #       return 0
        #   return var
        #
        # becomes:
        #   var0 = 1
        #   var1 = 2
        #   __return_value0 = 0
        #   __return_value1 = var0
        #   return __return_value0 if not cond else __return_value1
        #
        # instead of:
        #   var0 = 1
        #   var1 = 2
        #   __return_value0 = 0
        #   var2 = var0 if cond else var1
        #   __return_value1 = var2
        #   return __return_value0 if not cond else __return_value1


        # only care about new / modified names
        t_nt = t_nt.maps[0]
        f_nt = f_nt.maps[0]
        if t_returns and f_returns:
            # No need to mux any names they can't fall through anyway
            pass
        elif t_returns and not f_returns:
            # fall through from orelse
            nt.update(f_nt)
        elif f_returns and not t_returns:
            # fall through from body
            nt.update(t_nt)
        else:
            # mux names
            def _build_name(name):
                return ast.Name(
                        id=name,
                        ctx=ast.Load(),
                    )

            def _mux_name(name, t_name, f_name):
                return ast.Assign(
                        targets=[
                            ast.Name(
                                id=self._make_name(name),
                                ctx=ast.Store(),
                            ),
                        ],
                        value=ast.IfExp(
                            test=test,
                            body=_build_name(t_name),
                            orelse=_build_name(f_name),
                        ),
                    )

            # names in body, names in orelse
            for name in t_nt.keys() | f_nt.keys():
                if name in t_nt and name in f_nt:
                    # mux between true and false
                    suite.append(_mux_name(name, t_nt[name], f_nt[name]))
                elif name in t_nt and name in nt:
                    # mux between true and old value
                    suite.append(_mux_name(name, t_nt[name], nt[name]))
                elif name in f_nt and name in nt:
                    # mux between false and old value
                    suite.append(_mux_name(name, nt[name], f_nt[name]))

        return suite


    def visit_Name(self, node: ast.Name) -> ast.Name:
        name = node.id
        ctx = node.ctx
        if isinstance(ctx, ast.Load):
            return ast.Name(
                    id=self.name_table.setdefault(name, name),
                    ctx=ctx)
        else:
            return ast.Name(
                    id=self._make_name(name),
                    ctx=ctx)


    def visit_Return(self, node: ast.Return) -> ast.Assign:
        r_val = self.visit(node.value)
        r_name = self._make_return()
        self.returns.append((list(self.cond_stack), r_name))
        return ast.Assign(
            targets=[ast.Name(r_name, ast.Store())],
            value=r_val,
        )


    # don't support control flow other than if
    def visit_For(self, node: ast.For):
        raise SyntaxError(f"Cannot handle node {node}")

    def visit_AsyncFor(self, node: ast.AsyncFor):
        raise SyntaxError(f"Cannot handle node {node}")

    def visit_While(self, node: ast.While):
        raise SyntaxError(f"Cannot handle node {node}")

    def visit_With(self, node: ast.With):
        raise SyntaxError(f"Cannot handle node {node}")

    def visit_AsyncWith(self, node: ast.AsyncWith):
        raise SyntaxError(f"Cannot handle node {node}")

    def visit_Try(self, node: ast.Try):
        raise SyntaxError(f"Cannot handle node {node}")

    # don't recurs into defs, but do rename them
    def visit_ClassDef(self, node: ast.ClassDef):
        renamer = Renamer(self.name_table.new_child())
        return renamer.visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        renamer = Renamer(self.name_table.new_child())
        return renamer.visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        renamer = Renamer(self.name_table.new_child())
        return renamer.visit(node)


def _prove_names_defined(
        env: SymbolTable,
        names: tp.AbstractSet[str],
        node: tp.Union[ast.AST, tp.Sequence[ast.AST]]) -> tp.AbstractSet[str]:
    names = set(names)
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif node.id not in names and node.id not in env:
            if hasattr(node, 'lineno'):
                raise SyntaxError(f'Cannot prove name, {node.id}, is defined at line {node.lineno}')
            else:
                raise SyntaxError(f'Cannot prove name, {node.id}, is defined')

    elif isinstance(node, ast.If):
        t_returns = _always_returns(node.body)
        f_returns = _always_returns(node.orelse)
        t_names = _prove_names_defined(env, names, node.body)
        f_names = _prove_names_defined(env, names, node.orelse)
        if not (t_returns or f_returns):
            names |= t_names & f_names
        elif t_returns:
            names |= f_names
        elif f_returns:
            names |= t_names
    elif isinstance(node, ast.AST):
        for child in ast.iter_child_nodes(node):
            names |= _prove_names_defined(env, names, child)
    else:
        assert isinstance(node, tp.Sequence)
        for child in node:
            names |= _prove_names_defined(env, names, child)
    return names


def _always_returns(body: tp.Sequence[ast.stmt]) -> bool:
    for stmt in body:
        if isinstance(stmt, ast.Return):
            return True
        elif isinstance(stmt, ast.If):
            if _always_returns(stmt.body) and _always_returns(stmt.orelse):
                return True

    return False


def _build_return(
        returns: tp.Sequence[tp.Tuple[tp.List[ast.expr], str]]) -> ast.expr:
    assert returns
    conditions, name = returns[0]
    name = ast.Name(id=name, ctx=ast.Load())
    if not conditions or len(returns) == 1:
        return name
    else:
        expr = ast.IfExp(
            test=ast.BoolOp(
                op=ast.And(),
                values=conditions,
            ),
            body=name,
            orelse=_build_return(returns[1:]),
        )
        return expr


class ssa(Pass):
    def __init__(self, return_prefix: str = '__return_value'):
        self.return_prefix = return_prefix

    def rewrite(self, tree: ast.AST, env: SymbolTable):
        if not isinstance(tree, ast.FunctionDef):
            raise TypeError('ssa should only be applied to functions')
        r_name = gen_free_prefix(tree, env, self.return_prefix)
        visitor = SSATransformer(env, r_name)
        tree = visitor.visit(tree)
        tree.body.append(
            ast.Return(
                value=_build_return(visitor.returns)
            )
        )
        return tree, env
