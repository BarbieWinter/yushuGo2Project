import math
import logging
import threading
import time
from typing import Callable, Optional, Tuple

from config import (
    GO2_RPC_TIMEOUT,
    HANDSTAND_EXIT_SECONDS,
    MAX_VX,
    MAX_VY,
    MAX_VYAW,
    PATROL_BACKWARD_YAW_TRIM,
    PATROL_FORWARD_YAW_TRIM,
    PATROL_HEADING_KP,
    PATROL_HEADING_MAX_YAW,
    PATROL_ODOM_KP,
    PATROL_ODOM_MAX_YAW,
    WATCHDOG_TIMEOUT,
)


log = logging.getLogger("go2.rpc")


class Go2Controller:
    def __init__(
        self,
        interface: Optional[str],
        client=None,
        clock: Callable[[], float] = time.monotonic,
        heading: Optional[Callable[[], Optional[float]]] = None,
        pose: Optional[Callable[[], Optional[Tuple[float, float, float]]]] = None,
        walking_ready: Optional[Callable[[], Optional[bool]]] = None,
        connected: Optional[Callable[[], bool]] = None,
    ):
        self.interface = interface
        self._client = client
        self._clock = clock
        self._heading = heading
        self._pose = pose
        self._walking_ready = walking_ready
        self._connected = connected
        self._lock = threading.RLock()
        self._last_move_at = 0.0
        self._moving = False
        self._stop_pending = False
        self._cross_step_active = False
        self._handstand_active = False
        self._posture_blocked = False
        self._handstand_exit_until = 0.0
        self._cross_step_timer = None
        self._owner = ""
        self._sequences = {}
        self._heading_target = None
        self._odom_start = None
        self._last_error = ""

    @property
    def ready(self) -> bool:
        return self._client is not None

    def initialize(self) -> None:
        if self._client is not None:
            return

        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.go2.sport.sport_client import SportClient

        ChannelFactoryInitialize(0, self.interface)
        client = SportClient()
        client.SetTimeout(GO2_RPC_TIMEOUT)
        client.Init()
        self._client = client

    def move(
        self,
        vx: float,
        vy: float,
        vyaw: float,
        client_id: str = "",
        sequence: int = 0,
    ) -> Tuple[float, float, float, object, bool]:
        vx = self._clamp(vx, MAX_VX)
        vy = self._clamp(vy, MAX_VY)
        vyaw = self._clamp(vyaw, MAX_VYAW)

        with self._lock:
            self.require_transition_complete()
            if self._stop_pending:
                raise RuntimeError("停止尚未确认，请重试停止")
            walking_ready = self._walking_ready() if self._walking_ready is not None else None
            if self._posture_blocked or walking_ready is False:
                raise RuntimeError("当前姿态不能移动，请先点击起立或恢复站立")
            if self._moving and client_id != self._owner:
                return vx, vy, vyaw, None, False
            if self._cross_step_active or self._handstand_active:
                return vx, vy, vyaw, None, False
            if not self.move_sequence_valid(client_id, sequence):
                return vx, vy, vyaw, None, False
            if self._connected is not None and not self._connected():
                if self._moving:
                    self.stop()
                raise RuntimeError("机器人状态丢失，拒绝移动")
            self._remember_sequence(client_id, sequence)
            vyaw = self._clamp(self._hold_heading(vx, vy, vyaw), MAX_VYAW)
            self._last_move_at = self._clock()
            self._moving = True
            self._owner = client_id
            try:
                code = self._check(self._require_client().Move(vx, vy, vyaw), "Move")
            except Exception:
                self._stop_pending = True
                raise

        return vx, vy, vyaw, code, True

    def stop(self, client_id: str = "", sequence: int = 0):
        with self._lock:
            self._remember_sequence(client_id, sequence)
            walking_ready = self._walking_ready() if self._walking_ready is not None else None
            if ((self._posture_blocked or walking_ready is False)
                    and not self._cross_step_active
                    and not self._handstand_active):
                self._moving = False
                self._stop_pending = False
                self._owner = ""
                self._heading_target = None
                self._odom_start = None
                return 0
            self._stop_pending = True
            if self._cross_step_timer:
                self._cross_step_timer.cancel()
                self._cross_step_timer = None
            # Keep pending on either an exception or a nonzero SDK return code.
            try:
                if self._cross_step_active:
                    self._check(self._require_client().CrossStep(False), "CrossStep(False)")
                    self._cross_step_active = False
                if self._handstand_active:
                    self._check(self._require_client().HandStand(False), "HandStand(False)")
                    self._handstand_active = False
            finally:
                client = self._require_client()
                code = client.StopMove()
                if code == 3104:
                    # Best-effort zero velocity is not a StopMove acknowledgement.
                    try:
                        client.Move(0.0, 0.0, 0.0)
                    except Exception:
                        pass
                    # Retry only the idempotent stop, and require its acknowledgement.
                    code = client.StopMove()
                self._check(code, "StopMove")
            self._heading_target = None
            self._odom_start = None
            self._moving = False
            self._owner = ""
            self._stop_pending = False
            self._handstand_exit_until = 0.0
            return 0

    def stop_if_stale(self, timeout: float = WATCHDOG_TIMEOUT) -> bool:
        with self._lock:
            if not self._stop_pending and (
                not self._moving or (
                    self._clock() - self._last_move_at <= timeout
                    and (self._connected is None or self._connected())
                )
            ):
                return False
            self.stop()
            return True

    def stop_if_active(self) -> bool:
        with self._lock:
            if not (self._moving or self._cross_step_active
                    or self._handstand_active or self._stop_pending):
                return False
            self.stop()
            return True

    def set_straight_reference(self, heading: float) -> None:
        with self._lock:
            self._heading_target = heading if math.isfinite(heading) else None
            self._odom_start = None
            if self._heading_target is not None and self._pose is not None:
                pose = self._pose()
                if pose is not None and all(math.isfinite(value) for value in pose):
                    self._odom_start = (pose[0], pose[1])

    def move_sequence_valid(self, client_id, sequence):
        with self._lock:
            if not client_id:
                return True
            if client_id not in self._sequences and len(self._sequences) >= 128:
                raise RuntimeError("控制会话已满，请重启服务后重试；停止仍可使用")
            return sequence > self._sequences.get(client_id, 0)

    def _remember_sequence(self, client_id, sequence):
        # ponytail: 128 sessions per process lifetime; use expiring signed sessions if needed.
        # Never evict a stop watermark: that would allow an old move to restart motion.
        if client_id and (client_id in self._sequences or len(self._sequences) < 128):
            self._sequences[client_id] = max(sequence, self._sequences.get(client_id, 0))

    def _check(self, code, command):
        if code != 0:
            reason = (
                f"等待机器人应答超时（3104，RPC 阈值 {GO2_RPC_TIMEOUT:g}s），无法确认执行结果"
                if code == 3104 else
                "机器人拒绝停止（-1）；若处于姿态或特殊动作状态，"
                "请用遥控器切回普通行走状态后重试"
                if code == -1 and command == "StopMove" else
                f"SDK 返回错误码 {code}"
            )
            self._last_error = f"{command}: {reason}"
            raise RuntimeError(self._last_error)
        return code

    def status(self):
        return {"stop_pending": self._stop_pending, "last_error": self._last_error,
                "handstand_exiting": self._clock() < self._handstand_exit_until,
                "handstand_active": self._handstand_active,
                "rpc_timeout": GO2_RPC_TIMEOUT}

    def stand(self):
        with self._lock:
            self.require_transition_complete()
            self.stop_if_active()
            code = self._call("StandUp")
            self._posture_blocked = False
            return code

    def balance_stand(self):
        return self._set_posture("BalanceStand", True)

    def stand_down(self):
        return self._set_posture("StandDown", True)

    def recovery(self):
        return self._set_posture("RecoveryStand", False)

    def sit(self):
        return self._set_posture("Sit", True)

    def rise_sit(self):
        return self._set_posture("RiseSit", False)

    def hello(self):
        return self._call("Hello")

    def stretch(self):
        return self._call("Stretch")

    def heart(self):
        return self._call("Heart")

    def scrape(self):
        return self._call("Scrape")

    def front_jump(self):
        return self._call("FrontJump")

    def handstand(self):
        with self._lock:
            self.require_transition_complete()
            self.stop_if_active()
            # A timeout may still have entered the mode; stop must attempt to exit it.
            self._handstand_active = True
            try:
                return self._call("HandStand", True)
            except Exception:
                if not self._stop_pending:
                    self._handstand_active = False
                raise

    def exit_handstand(self):
        with self._lock:
            if self._stop_pending:
                raise RuntimeError("停止尚未确认，请使用立即停止")
            if not self._handstand_active:
                return 0
            # Let firmware perform its exit; acknowledgement is not landing completion.
            try:
                code = self._call("HandStand", False)
            except Exception:
                self._stop_pending = True
                raise
            self._handstand_active = False
            self._handstand_exit_until = self._clock() + HANDSTAND_EXIT_SECONDS
            return code

    def require_transition_complete(self):
        with self._lock:
            if self._clock() < self._handstand_exit_until:
                raise RuntimeError("倒立退出等待中，请稍后操作；立即停止仍可使用")

    def cross_step(self, duration: float = 2.0):
        with self._lock:
            self.require_transition_complete()
            if self._stop_pending:
                raise RuntimeError("停止尚未确认")
            if self._cross_step_timer:
                self._cross_step_timer.cancel()
            self._cross_step_active = True
            try:
                self._check(self._require_client().CrossStep(True), "CrossStep(True)")
            except Exception:
                self._stop_pending = True
                raise
            timer = threading.Timer(duration, lambda: self._finish_cross_step(timer))
            timer.daemon = True
            self._cross_step_timer = timer
            timer.start()
        return 0, None

    def _finish_cross_step(self, timer):
        with self._lock:
            if self._cross_step_timer is not timer:
                return
            try:
                self.stop()
            except Exception:
                # stop() leaves the pending flag for watchdog retries.
                pass

    def _call(self, method: str, *args):
        with self._lock:
            self.require_transition_complete()
            if self._stop_pending:
                raise RuntimeError("停止尚未确认")
            try:
                code = getattr(self._require_client(), method)(*args)
            except Exception:
                self._stop_pending = True
                raise
            if code == 3104:
                self._stop_pending = True
            return self._check(code, method)

    def _set_posture(self, method: str, blocked: bool):
        code = self._call(method)
        self._posture_blocked = blocked
        return code

    def _require_client(self):
        if self._client is None:
            raise RuntimeError("Go2 controller is not initialized")
        return self._client

    def _hold_heading(self, vx: float, vy: float, vyaw: float) -> float:
        if self._heading is None or vx == 0 or vy != 0 or vyaw != 0:
            self._heading_target = None
            return vyaw
        current = self._heading()
        if current is None or not math.isfinite(current):
            self._heading_target = None
            self._odom_start = None
            return vyaw
        if self._heading_target is None:
            self._heading_target = current
            if self._pose is not None:
                pose = self._pose()
                if pose is not None and all(math.isfinite(value) for value in pose):
                    self._odom_start = (pose[0], pose[1])
        trim = PATROL_FORWARD_YAW_TRIM if vx > 0 else PATROL_BACKWARD_YAW_TRIM
        error = (current - self._heading_target + math.pi) % (2 * math.pi) - math.pi
        yaw = trim - PATROL_HEADING_KP * error
        if self._pose is not None and self._odom_start is not None:
            pose = self._pose()
            if pose is not None and all(math.isfinite(value) for value in pose):
                dx = pose[0] - self._odom_start[0]
                dy = pose[1] - self._odom_start[1]
                lateral_error = (
                    -math.sin(self._heading_target) * dx
                    + math.cos(self._heading_target) * dy
                )
                direction = 1.0 if vx > 0 else -1.0
                odom_yaw = self._clamp(
                    -direction * PATROL_ODOM_KP * lateral_error,
                    PATROL_ODOM_MAX_YAW,
                )
                output = self._clamp(yaw + odom_yaw, PATROL_HEADING_MAX_YAW)
                log.info(
                    "event=straight_control vx=%.3f heading=%.4f target=%.4f "
                    "heading_error=%.4f lateral_error=%.4f imu_yaw=%.4f "
                    "odom_yaw=%.4f output_yaw=%.4f",
                    vx, current, self._heading_target, error, lateral_error,
                    yaw, odom_yaw, output,
                )
                return output
        return self._clamp(yaw, PATROL_HEADING_MAX_YAW)

    @staticmethod
    def _clamp(value: float, limit: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return max(-limit, min(value, limit))
