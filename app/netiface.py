"""查找与机器人同网段的本机网卡，换电脑时不需要改网卡名。

Unitree Go2 的机载网络是 192.168.123.x，本机与机器人相连的网卡会持有该网段
地址，这里按地址反查网卡：Windows 返回适配器别名（如“以太网”“Ethernet”），
Linux / macOS 返回 eth0、en8 这类接口名。找不到时返回 None，交给
CycloneDDS 自行选择。
"""

import locale
import os
import re
import subprocess
import sys

ROBOT_SUBNET_PREFIX = "192.168.123."
_TIMEOUT_SECONDS = 3.0

_IP_ADDR_LINE = re.compile(r"^\d+:\s+([^\s:]+)\s+inet\s+([0-9.]+)/")
_IFCONFIG_HEAD = re.compile(r"^([^\s:]+):")
_IFCONFIG_INET = re.compile(r"\binet\s+(?:addr:)?([0-9.]+)")


def _matches_robot_subnet(address: str) -> bool:
    return address.startswith(ROBOT_SUBNET_PREFIX)


def _decoded(raw: bytes) -> str:
    for encoding in ("utf-8", locale.getpreferredencoding(False), "mbcs"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _run(*command: str) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return _decoded(result.stdout)


def parse_ip_addr_output(output: str) -> str | None:
    """解析 `ip -o -4 addr show` 的输出。"""
    for line in output.splitlines():
        match = _IP_ADDR_LINE.match(line)
        if match and _matches_robot_subnet(match.group(2)):
            return match.group(1)
    return None


def parse_ifconfig_output(output: str) -> str | None:
    """解析 macOS / Linux 的 ifconfig 输出。"""
    iface = None
    for line in output.splitlines():
        head = _IFCONFIG_HEAD.match(line)
        if head:
            iface = head.group(1)
            continue
        match = _IFCONFIG_INET.search(line)
        if iface and match and _matches_robot_subnet(match.group(1)):
            return iface
    return None


def _detect_windows() -> str | None:
    # 显式切到 UTF-8，中文 Windows 上别名（如“以太网”）不会乱码。
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-NetIPAddress -AddressFamily IPv4 | "
        f"Where-Object {{ $_.IPAddress -like '{ROBOT_SUBNET_PREFIX}*' }} | "
        "Select-Object -First 1 -ExpandProperty InterfaceAlias"
    )
    for line in _run("powershell.exe", "-NoProfile", "-Command", script).splitlines():
        alias = line.strip()
        if alias:
            return alias
    return None


def _detect_posix() -> str | None:
    detected = parse_ip_addr_output(_run("ip", "-o", "-4", "addr", "show"))
    if detected is not None:
        return detected
    return parse_ifconfig_output(_run("ifconfig"))


def detect_robot_iface() -> str | None:
    """返回网卡名：显式设置的 GO2_IFACE 优先，否则自动检测；找不到返回 None。"""
    explicit = os.getenv("GO2_IFACE", "").strip()
    if explicit:
        return explicit
    if sys.platform == "win32":
        return _detect_windows()
    return _detect_posix()
