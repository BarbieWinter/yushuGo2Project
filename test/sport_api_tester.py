"""按 API ID 交互测试 Go2 运动指令。

用法：
  .venv/bin/python test/sport_api_tester.py --iface en8
  .venv/bin/python test/sport_api_tester.py --list
  .venv/bin/python test/sport_api_tester.py --no-confirm

输入格式：
  1004                  # 无参数指令，直接执行
  1007 0.05 0 0         # 带参数指令，依次给出 roll pitch yaw
  1015 2                # SpeedLevel
  list                  # 列出全部 API ID
  q                     # 退出

API ID 与方法名的对应关系从 SDK 源码自动解析，不在本文件里写死。
"""

import argparse
import inspect
import re
import subprocess
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.sport import sport_api
from unitree_sdk2py.go2.sport.sport_client import SportClient

MOVE_HOLD_SECONDS = 1.5   # Move 非零速度自动保持时长，之后自动 StopMove
MOVE_HOLD_HZ = 20.0       # Move 保持期间的发送频率


def detect_robot_iface():
    """查找持有 192.168.123.x 地址的网卡。"""
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    iface = None
    for line in out.splitlines():
        head = re.match(r"^([a-zA-Z0-9_.-]+):", line)
        if head:
            iface = head.group(1)
        elif iface and re.search(r"inet 192\.168\.123\.\d+", line):
            return iface
    return None


def build_api_map():
    """扫描 SportClient 的方法源码，提取每个方法使用的 SPORT_API_ID_*。"""
    api_map = {}
    for name in dir(SportClient):
        if name.startswith("_") or name == "Init":
            continue
        func = getattr(SportClient, name)
        if not inspect.isfunction(func):
            continue
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError):
            continue
        match = re.search(r"SPORT_API_ID_([A-Z0-9_]+)", source)
        if not match:
            continue
        api_id = getattr(sport_api, "SPORT_API_ID_" + match.group(1), None)
        if api_id is not None:
            api_map[api_id] = name
    return api_map


def method_params(name):
    """返回方法除 self 外的参数列表。"""
    sig = inspect.signature(getattr(SportClient, name))
    return [p for p in sig.parameters.values() if p.name != "self"]


def coerce(value, annotation):
    """按类型注解把输入字符串转成 float / int / bool。"""
    if annotation is bool:
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on", "y"):
            return True
        if text in ("0", "false", "no", "off", "n"):
            return False
        raise ValueError("需要 true/false 或 1/0")
    if annotation is int:
        return int(value)
    if annotation is float:
        return float(value)
    return value


def prompt_params(name, args):
    """把命令行参数补齐成方法需要的参数。"""
    params = method_params(name)
    if len(args) > len(params):
        raise ValueError(f"{name} 只需要 {len(params)} 个参数")
    values = []
    for index, param in enumerate(params):
        if index < len(args):
            values.append(coerce(args[index], param.annotation))
            continue
        # 缺参数时逐个询问，直接回车使用默认值
        default = 0.0 if param.annotation is float else 0 if param.annotation is int else False
        hint = getattr(param.annotation, "__name__", str(param.annotation))
        raw = input(f"  参数 {param.name} ({hint}) [{default}]: ").strip()
        values.append(default if raw == "" else coerce(raw, param.annotation))
    return values


def print_api_list(api_map):
    for api_id in sorted(api_map):
        name = api_map[api_id]
        params = ", ".join(
            f"{p.name}: {getattr(p.annotation, '__name__', p.annotation)}"
            for p in method_params(name)
        )
        print(f"{api_id:>5}  {name:<18} ({params})")


def execute(client, api_map, line):
    """执行一行输入。返回 False 表示退出。"""
    line = line.strip()
    if not line:
        return True
    if line in ("q", "quit", "exit"):
        return False
    if line == "list":
        print_api_list(api_map)
        return True

    parts = line.split()
    try:
        api_id = int(parts[0])
    except ValueError:
        print("输入无效：第一项必须是 API ID，或 list / q")
        return True

    name = api_map.get(api_id)
    if name is None:
        print(f"未知 API ID: {api_id}，输入 list 查看全部")
        return True

    try:
        args = prompt_params(name, parts[1:])
    except (ValueError, EOFError) as exc:
        print(f"参数错误：{exc}")
        return True

    method = getattr(client, name)
    print(f"[执行] {api_id} {name}{tuple(args)}")
    started = time.time()

    # Move 是持续速度指令：非零速度时保持一段时间，再自动停车
    if name == "Move" and any(v != 0 for v in args):
        vx, vy, vyaw = args
        code = 0
        try:
            for _ in range(int(MOVE_HOLD_SECONDS * MOVE_HOLD_HZ)):
                code = client.Move(vx, vy, vyaw)
                if code != 0:
                    break
                time.sleep(1.0 / MOVE_HOLD_HZ)
        finally:
            stop_code = client.StopMove()
        print(f"[结果] Move code={code}, 自动 StopMove code={stop_code}, "
              f"保持 {MOVE_HOLD_SECONDS}s")
        return True

    try:
        result = method(*args)
    except Exception as exc:
        print(f"[异常] {type(exc).__name__}: {exc}")
        return True

    print(f"[结果] code={result}  耗时 {time.time() - started:.3f}s")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iface", default=None, help="网卡名，例如 en8")
    parser.add_argument("--domain", type=int, default=0)
    parser.add_argument("--list", action="store_true", help="只列出 API ID 后退出")
    parser.add_argument("--no-confirm", action="store_true", help="跳过启动前的安全确认")
    args = parser.parse_args()

    api_map = build_api_map()
    if not api_map:
        print("没有从 SDK 解析到任何 API ID")
        return 1

    if args.list:
        print_api_list(api_map)
        return 0

    iface = args.iface or detect_robot_iface()
    if iface is None:
        print("找不到 192.168.123.x 网卡，请用 --iface 指定")
        return 1
    print(f"使用网卡: {iface}")

    if not args.no_confirm:
        print("警告：部分动作（空翻、跳扑、倒立）有风险。确认机器人周围无人、地面平整。")
        answer = input("回车继续，输入 q 退出: ").strip().lower()
        if answer in ("q", "quit", "exit"):
            return 0

    ChannelFactoryInitialize(args.domain, iface)

    client = SportClient()
    client.SetTimeout(5.0)
    client.Init()

    # 先探测 sport 服务是否可用；失败仍允许继续，便于观察具体错误码
    version = client.GetServerApiVersion()
    if version[0] != 0:
        print(f"[警告] sport 服务无应答: {version}，后续指令可能都返回 3102")
    else:
        print(f"sport 服务版本: {version[1]}")

    print("输入 API ID 执行，list 查看列表，q 退出")
    while True:
        try:
            line = input("API ID> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not execute(client, api_map, line):
            break
    print("退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
