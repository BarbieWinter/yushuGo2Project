"""Exercise the SDK receive path without loading DDS or connecting to hardware."""
import ast
import importlib.util
import logging
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


def _client_stub_source() -> Path:
    """定位当前环境实际使用的 SDK，兼容可编辑安装和源码目录布局。"""
    spec = importlib.util.find_spec("unitree_sdk2py")
    if spec is None or spec.origin is None:
        pytest.skip("unitree_sdk2py not installed")
    source = Path(spec.origin).resolve().parent / "rpc" / "client_stub.py"
    if not source.exists():
        pytest.skip(f"client_stub.py not found: {source}")
    if "_trace" not in source.read_text(encoding="utf-8"):
        pytest.skip("installed SDK has no RPC trace patch")
    return source


def test_rpc_trace_keeps_late_responses(caplog):
    source = _client_stub_source()
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    pending = {}
    namespace = {
        "time": time, "logging": logging, "Request": object, "Response": object,
        "RequestFuture": lambda: NS(SetRequestId=lambda value: None, Ready=lambda response: True),
    }
    exec(compile(tree, str(source), "exec"), namespace)
    stub = namespace["ClientStub"]("sport")
    stub._ClientStub__futureQueue = NS(
        Set=lambda key, value: pending.update({key: value}),
        Get=pending.get, Remove=lambda key: pending.pop(key, None),
    )
    stub._ClientStub__sendChannel = NS(Write=lambda request, timeout: True)
    message = NS(header=NS(identity=NS(id=123, api_id=1031), status=NS(code=0)))
    with caplog.at_level(logging.INFO, logger="go2.rpc"):
        stub.SendRequest(message, 1.0)
        stub.RemoveFuture(123)
        stub._trace("wait_failed", message, code=3104, timeout=1.0)
        stub._ClientStub__ResponseHandler(message)
    assert "event=send_request" in caplog.text
    assert "event=write" in caplog.text and "ok=True" in caplog.text
    assert "code=3104" in caplog.text
    assert "event=response" in caplog.text and "matched=False" in caplog.text
    assert "id=123 api=1031" in caplog.text
