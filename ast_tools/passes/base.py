from abc import ABCMeta, abstractmethod
import ast
import typing as tp

from ast_tools.stack import SymbolTable

__ALL__ = ['Pass', 'PASS_ARGS_T']

PASS_ARGS_T = tp.Tuple[ast.AST, SymbolTable]

class Pass(metaclass=ABCMeta):
    """
    Abstract base class for passes
    Mostly a convience to unpack arguments
    """

    def __call__(self, args: PASS_ARGS_T) -> PASS_ARGS_T:
        return self.rewrite(*args)

    @abstractmethod
    def rewrite(self,
            env: SymbolTable,
            tree: ast.AST,
            ) -> PASS_ARGS_T:

        """
        Type annotation here should be followed except on terminal passes e.g.
        end_rewite
        """
        pass
