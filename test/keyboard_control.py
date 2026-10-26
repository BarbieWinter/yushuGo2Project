"""Go2 键盘遥控示例（基于 Unitree SDK2 Python）。

按键说明：
  W / S  ：前进 / 后退
  A / D  ：左转 / 右转
  空格   ：站立 / 趴下 切换
  O      ：避障模式开 / 关
  Q      ：退出（退出前发送 StopMove）

运行方式：
  .venv/bin/python test/keyboard_control.py --iface en8
未指定 --iface 时，会自动查找持有 192.168.123.x 地址的网卡。
"""

import argparse
import re
import select
import subprocess
import sys
import termios
import time
import tty

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.go2.obstacles_avoid.obstacles_avoid_client import ObstaclesAvoidClient
from unitree_sdk2py.go2.sport.sport_client import SportClient
from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

VX_SPEED = 0.5      # 前进/后退线速度，单位 m/s
VYAW_SPEED = 0.8    # 转向角速度，单位 rad/s
KEY_TIMEOUT = 0.6   # 超过该时间没有收到按键（系统按键重复），自动停车，单位 s
LOOP_DT = 0.1       # 主循环周期，10 Hz
MOVE_CODE_OK = 0    # 运动服务返回 0 表示指令执行成功

# 站立时 body_height 约 0.32 m，趴下时明显低于 0.2 m。
# error_code 不能可靠判断姿态（实测出现过 100、1001、1002），因此用高度判断。
STANDING_HEIGHT = 0.20


class KeyboardTeleop:
    """把按键状态转换成运动服务调用。"""

    def __init__(self, sport: SportClient, avoid: ObstaclesAvoidClient, standing: bool):
        self.sport = sport              # 运动服务客户端
        self.avoid = avoid              # 避障服务客户端
        self.standing = standing        # 当前是否站立
        self.vx = 0.0                   # 当前线速度指令
        self.vyaw = 0.0                 # 当前角速度指令
        self.last_key_time = 0.0        # 最后一次收到移动按键的时刻
        self.is_moving = False          # 是否已下发过运动指令
        self.busy_until = 0.0           # 姿态切换期间屏蔽运动的截止时刻
        self.avoid_enabled = False      # 避障模式是否已开启
        self.avoid_busy_until = 0.0     # 避障开关防抖截止时刻

    def handle_key(self, key: str) -> bool:
        """处理单个按键。返回 False 表示退出主循环。"""
        now = time.time()
        if key == "q":
            return False

        # 空格：站立 / 趴下切换
        if key == " ":
            self.stop_motion()
            if now < self.busy_until:
                print("[skip] still changing posture")
                return True
            if self.standing:
                code = self.sport.StandDown()
                self.standing = False
                self.busy_until = now + 3.0     # 趴下动作约需数秒，期间不响应移动
                print(f"[posture] StandDown -> {code}")
            else:
                code = self.sport.StandUp()
                self.standing = True
                self.busy_until = now + 3.0     # 站起动作约需数秒，期间不响应移动
                print(f"[posture] StandUp -> {code}")
            return True

        # O：避障模式开关。避障是持续生效的模式，按下时切换一次即可，
        # 不需要在循环里反复调用；但运动指令仍由 tick() 每周期发送。
        if key in "oO":
            self.toggle_avoid()
            return True

        # WASD：设置速度指令。终端按键重复会持续刷新 last_key_time，
        # 松开按键后由 tick() 的超时逻辑自动停车。
        if key in "wasd":
            if not self.standing:
                print("[skip] robot is lying down, press Space to stand up")
                return True
            if now < self.busy_until:
                print("[skip] still changing posture")
                return True
            self.vx = VX_SPEED if key == "w" else -VX_SPEED if key == "s" else 0.0
            self.vyaw = VYAW_SPEED if key == "a" else -VYAW_SPEED if key == "d" else 0.0
            self.last_key_time = now
        return True

    def sync_avoid_state(self):
        """读取机器人当前避障开关，避免本地状态与实际不一致。"""
        code, enabled = self.avoid.SwitchGet()
        if code != MOVE_CODE_OK:
            print(f"[avoid] state query failed -> {code}")
            return
        self.avoid_enabled = bool(enabled)
        if self.avoid_enabled:
            self.avoid.UseRemoteCommandFromApi(True)
        print(f"[avoid] current: {'on' if self.avoid_enabled else 'off'}")

    def toggle_avoid(self):
        """切换避障模式。官方流程：UseRemoteCommandFromApi + SwitchSet，
        再轮询 SwitchGet 确认；只在切换时执行，不在每个控制周期重复。"""
        now = time.time()
        if now < self.avoid_busy_until:
            return                                  # 防抖，忽略按住 O 产生的重复按键
        self.avoid_busy_until = now + 1.0

        if self.avoid_enabled:
            self.disable_avoid()
            return

        code = self.avoid.UseRemoteCommandFromApi(True)
        if code != MOVE_CODE_OK:
            print(f"[avoid] enable failed: UseRemoteCommandFromApi -> {code}")
            return

        enabled = False
        set_code = get_code = None
        for _ in range(3):
            set_code = self.avoid.SwitchSet(True)
            get_code, enabled = self.avoid.SwitchGet()
            if get_code != MOVE_CODE_OK:
                break                               # 服务不可用，直接放弃
            if enabled:
                break
            time.sleep(0.2)

        if enabled:
            self.avoid_enabled = True
            print("[avoid] on")
        else:
            self.avoid.UseRemoteCommandFromApi(False)
            print(f"[avoid] enable failed: SwitchSet={set_code}, SwitchGet={get_code}")

    def disable_avoid(self):
        """关闭避障模式。退出前也应调用，避免机器人保持避障模式。"""
        self.stop_motion()
        code = self.avoid.SwitchSet(False)
        self.avoid.UseRemoteCommandFromApi(False)
        self.avoid_enabled = False
        print(f"[avoid] off -> {code}")

    def tick(self):
        """按固定周期下发运动指令，或在按键松开后停车。"""
        now = time.time()
        if now < self.busy_until:
            return                                  # 姿态切换中，不下发运动
        if self.vx == 0.0 and self.vyaw == 0.0:
            return                                  # 当前无运动指令
        if now - self.last_key_time > KEY_TIMEOUT:
            self.stop_motion()                      # 按键已松开，超时停车
            return
        # 避障模式下必须把速度指令发给避障服务，运动服务不会自动避障
        move_client = self.avoid if self.avoid_enabled else self.sport
        code = move_client.Move(self.vx, 0.0, self.vyaw)
        if code != MOVE_CODE_OK:
            print(f"[move] rejected -> {code}")     # 例如未站立时机器人会拒绝
            self.stop_motion()
            return
        self.is_moving = True

    def stop_motion(self):
        """清零速度并发送 StopMove（仅在之前确实运动过时发送）。"""
        self.vx = 0.0
        self.vyaw = 0.0
        if self.is_moving:
            code = self.sport.StopMove()
            print(f"[move] StopMove -> {code}")
            self.is_moving = False


def detect_robot_iface():
    """解析 ifconfig，返回持有 192.168.123.x 地址的网卡名。"""
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    iface = None
    for line in out.splitlines():
        # 网卡块以 "en8:" 这类行开头，后续 inet 行属于该网卡
        head = re.match(r"^([a-zA-Z0-9_.-]+):", line)
        if head:
            iface = head.group(1)
        elif iface and re.search(r"inet 192\.168\.123\.\d+", line):
            return iface
    return None


def read_initial_state(timeout: float = 2.0):
    """订阅 rt/sportmodestate 并等待一帧，用于判断初始姿态。"""
    box = {}
    sub = ChannelSubscriber("rt/sportmodestate", SportModeState_)
    sub.Init(lambda msg: box.__setitem__("msg", msg), 10)
    deadline = time.time() + timeout
    while time.time() < deadline and "msg" not in box:
        time.sleep(0.05)
    if "msg" not in box:
        return None
    return box["msg"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iface", default=None, help="网卡名，例如 en8")
    parser.add_argument("--domain", type=int, default=0)
    parser.add_argument("--avoid", action="store_true", help="启动时默认开启避障")
    args = parser.parse_args()

    # 未指定网卡时自动检测，避免 DDS 自动选择连错网卡
    if args.iface is None:
        args.iface = detect_robot_iface()
        if args.iface is None:
            print("no interface with a 192.168.123.x address; pass --iface <name>")
            return 1
        print(f"auto-detected interface: {args.iface}")

    # 初始化 DDS 通信，domain 与机器人一致（默认 0）
    ChannelFactoryInitialize(args.domain, args.iface)

    state = read_initial_state()
    if state is None:
        print("no rt/sportmodestate data, check network / interface")
        return 1

    standing = state.body_height > STANDING_HEIGHT
    print(f"robot state: mode={state.mode} error_code={state.error_code} "
          f"body_height={state.body_height:.3f} "
          f"-> {'standing' if standing else 'lying'}")
    print("W/S forward/back, A/D turn, Space stand/down, O obstacle avoidance, Q quit")

    sport = SportClient()
    sport.SetTimeout(5.0)
    sport.Init()

    avoid = ObstaclesAvoidClient()
    avoid.SetTimeout(2.0)
    avoid.Init()

    teleop = KeyboardTeleop(sport, avoid, standing)
    teleop.sync_avoid_state()
    if args.avoid and not teleop.avoid_enabled:
        teleop.toggle_avoid()

    # cbreak 模式：单键读取，无需回车，同时保留 Ctrl-C
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            # 有按键就处理；没有按键也继续走 tick()，保证运动指令持续下发
            if select.select([sys.stdin], [], [], LOOP_DT)[0]:
                key = sys.stdin.read(1)
                if not teleop.handle_key(key):
                    break
            teleop.tick()
    except KeyboardInterrupt:
        pass
    finally:
        # 无论正常退出还是 Ctrl-C，都恢复终端设置并让机器人停下
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        teleop.stop_motion()
        if teleop.avoid_enabled:
            teleop.disable_avoid()          # 退出时关闭避障，避免模式残留
        print("bye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
