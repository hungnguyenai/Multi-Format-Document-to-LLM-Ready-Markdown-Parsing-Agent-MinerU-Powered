# TC-06 / TC-07 — framework compliance:
#
#   TC-06: _security_gate_input() is non-bypassable on FunctionNode — a domain
#          subclass that overrides it directly must fail at class-definition
#          time (FunctionNode.__init_subclass__ raises TypeError).
#   TC-07: _security_gate_output() is non-bypassable on FunctionNode — same
#          enforcement.
#
# Both gates are @final on FunctionNode; domain nodes may only extend them via
# the _extra_security_gate_input() / _extra_security_gate_output() hooks.
#
# Generic / repo-agnostic: discovers every concrete FunctionNode subclass under
# src/nodes/ dynamically (same discovery approach as
# tests/proof_of_boundary/test_pb_invoke_order.py) rather than hardcoding node
# class names, so this file is identical across templates.
#
# GraphNode / RemoteAgentNode subclasses are out of scope — they implement
# their own gate methods without FunctionNode's __init_subclass__ enforcement
# (framework.nodes.function_node.FunctionNode docstring).

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest


def _discover_function_node_subclasses() -> list[type]:
    """Import every module under src/nodes/ and collect concrete FunctionNode subclasses."""
    from framework.nodes.function_node import FunctionNode

    try:
        pkg = importlib.import_module("src.nodes")
    except ImportError:
        return []

    discovered = []
    for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix="src.nodes."):
        module = importlib.import_module(modname)
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, FunctionNode)
                and attr is not FunctionNode
                and attr.__module__ == modname
                and not inspect.isabstract(attr)
            ):
                discovered.append(attr)
    return discovered


_NODE_CLASSES = _discover_function_node_subclasses()


class TestTC06SecurityGateInputNonBypassable:
    """TC-06: _security_gate_input() cannot be overridden by domain nodes."""

    def test_overriding_security_gate_input_raises_for_every_node(self):
        if not _NODE_CLASSES:
            pytest.skip("no concrete FunctionNode subclasses found under src/nodes/")

        for node_cls in _NODE_CLASSES:
            with pytest.raises(TypeError, match="_security_gate_input"):
                type(
                    f"Bad{node_cls.__name__}Input",
                    (node_cls,),
                    {"_security_gate_input": lambda self, state: state},
                )

    def test_extra_security_gate_input_hook_is_the_correct_extension_point(self):
        if not _NODE_CLASSES:
            pytest.skip("no concrete FunctionNode subclasses found under src/nodes/")

        node_cls = _NODE_CLASSES[0]
        # The hook (not the @final gate) is the sanctioned override point —
        # this must NOT raise.
        extended = type(
            f"Extended{node_cls.__name__}",
            (node_cls,),
            {"_extra_security_gate_input": lambda self, state: state},
        )
        assert extended is not None


class TestTC07SecurityGateOutputNonBypassable:
    """TC-07: _security_gate_output() cannot be overridden by domain nodes."""

    def test_overriding_security_gate_output_raises_for_every_node(self):
        if not _NODE_CLASSES:
            pytest.skip("no concrete FunctionNode subclasses found under src/nodes/")

        for node_cls in _NODE_CLASSES:
            with pytest.raises(TypeError, match="_security_gate_output"):
                type(
                    f"Bad{node_cls.__name__}Output",
                    (node_cls,),
                    {"_security_gate_output": lambda self, result: result},
                )

    def test_extra_security_gate_output_hook_is_the_correct_extension_point(self):
        if not _NODE_CLASSES:
            pytest.skip("no concrete FunctionNode subclasses found under src/nodes/")

        node_cls = _NODE_CLASSES[0]
        extended = type(
            f"Extended{node_cls.__name__}",
            (node_cls,),
            {"_extra_security_gate_output": lambda self, result: result},
        )
        assert extended is not None
