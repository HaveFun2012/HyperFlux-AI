"""Evaluate simple arithmetic without running arbitrary code."""

import ast
import operator as op
import re


class SafeMathSolver:
    operators = {
        ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
        ast.Div: op.truediv, ast.Pow: op.pow, ast.USub: op.neg, ast.Mod: op.mod
    }

    @classmethod
    def _eval_node(cls, node):
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            return cls.operators[type(node.op)](cls._eval_node(node.left), cls._eval_node(node.right))
        elif isinstance(node, ast.UnaryOp):
            return cls.operators[type(node.op)](cls._eval_node(node.operand))
        else:
            raise TypeError(f"Unsupported math operation: {node}")

    @classmethod
    def solve(cls, expression):
        try:
            clean = re.sub(r'[^\d+\-*/().\s%]', '', expression)
            if clean.strip():
                node = ast.parse(clean, mode='eval')
                result = cls._eval_node(node.body)
                return f"Calculated value: **{result}**"
        except Exception:
            pass
        return None
