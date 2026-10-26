import json
import logging
import math
import threading
import time

from config import (
    MAX_VX,
    MAX_VY,
    MAX_VYAW,
    PATROL_FORWARD_SECONDS,
    PATROL_JOIN_TIMEOUT,
    PATROL_SETTLE_SECONDS,
    PATROL_TURN_CONTROL_INTERVAL,
    PATROL_TURN_KP,
    PATROL_TURN_HOLD_SECONDS,
    PATROL_TURN_MIN_YAW,
    PATROL_TURN_SETTLE_TOLERANCE,
    PATROL_TURN_SECONDS,
    PATROL_TURN_TIMEOUT_MARGIN,
    PATROL_TURN_TOLERANCE,
)


log = logging.getLogger(__name__)
FIXED_ANGLES = {
    "turn_left_90": math.pi / 2,
    "turn_right_90": -math.pi / 2,
    "turn_left_180": math.pi,
    "turn_right_180": -math.pi,
}
DISTANCE_ACTIONS = {"forward_distance", "backward_distance"}


class PatrolController:
    def __init__(self, controller, state_reader, path_file=None):
        self.controller = controller
        self.state_reader = state_reader
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._status = "idle"
        self._reason = ""
        self._path_file = path_file
        self._path = [
            {"action": "forward", "duration": PATROL_FORWARD_SECONDS},
            {"action": "turn_left", "duration": PATROL_TURN_SECONDS},
        ]
        if self._path_file and self._path_file.exists():
            try:
                ok, message = self.set_path(json.loads(self._path_file.read_text(encoding="utf-8")))
                if not ok:
                    log.warning("Saved patrol path is invalid (%s); using default", message)
            except (OSError, ValueError, TypeError):
                log.exception("Saved patrol path is invalid; using default")

    def path(self):
        with self._lock:
            return [step.copy() for step in self._path]

    def set_path(self, steps):
        if not isinstance(steps, list):
            return False, "巡逻路径格式无效"
        if not 1 <= len(steps) <= 20:
            return False, "巡逻路径需要 1 至 20 个步骤"

        allowed = {
            "forward", "backward", "left", "right", "wait",
            "turn_left", "turn_right", *FIXED_ANGLES, *DISTANCE_ACTIONS,
        }
        path = []
        for step in steps:
            if not isinstance(step, dict) or "action" not in step:
                return False, "巡逻步骤格式无效"
            action = str(step["action"])
            if action not in allowed:
                return False, "巡逻动作无效"
            if action in DISTANCE_ACTIONS:
                try:
                    distance = float(step.get("distance", 0))
                except (TypeError, ValueError):
                    return False, "前进/后退距离必须为数字"
                if not math.isfinite(distance) or not 0.05 <= distance <= 20.0:
                    return False, "前进/后退距离必须为 0.05 至 20 米"
                path.append({"action": action, "distance": distance})
                continue
            try:
                duration = float(
                    step.get("duration", abs(FIXED_ANGLES.get(action, 0)) / MAX_VYAW)
                )
            except (TypeError, ValueError):
                return False, "巡逻步骤时长必须为数字"
            if not math.isfinite(duration) or not 0.1 <= duration <= 60.0:
                return False, "每个步骤时长必须为 0.1 至 60 秒"
            if action in FIXED_ANGLES and duration > 10.0:
                return False, "定角转向校准时间必须为 0.1 至 10 秒"
            path.append({"action": action, "duration": duration})

        with self._lock:
            if self._thread and self._thread.is_alive():
                return False, "请先停止巡逻"
            if self._path_file:
                try:
                    temporary = self._path_file.with_suffix(".tmp")
                    temporary.write_text(json.dumps(path, ensure_ascii=False), encoding="utf-8")
                    temporary.replace(self._path_file)
                except OSError:
                    log.exception("Unable to save patrol path")
                    return False, "巡逻路径文件保存失败"
            self._path = path
        return True, "巡逻路径已保存"

    def start(self, vx=MAX_VX, vyaw=MAX_VYAW):
        if not all(math.isfinite(v) and v > 0 for v in (vx, vyaw)):
            return False, "巡逻速度必须为有限正数"
        vx, vyaw = min(vx, MAX_VX), min(vyaw, MAX_VYAW)
        state = self.state_reader.snapshot()
        path = self.path()
        if not state["connected"]:
            return False, "机器人状态未连接"
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False, "巡逻已经运行"
            self._stop_event.clear()
            self._status = "running"
            self._reason = ""
            self._thread = threading.Thread(
                target=self._run, args=(path, abs(vx), abs(vyaw)), name="go2-patrol", daemon=True
            )
            self._thread.start()
        return True, "巡逻已启动"

    def stop(self):
        with self._lock:
            thread = self._thread
        running = bool(thread and thread.is_alive())
        if running:
            self._stop_event.set()
            thread.join(timeout=PATROL_JOIN_TIMEOUT)
        if thread and thread.is_alive():
            self._set_status("stopping", "正在等待控制调用返回")
        else:
            self._set_status("idle", "")
        return running

    def running(self):
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def snapshot(self):
        with self._lock:
            return {"status": self._status, "reason": self._reason}

    def _run(self, path, forward_speed, turn_speed):
        commands = {
            "forward": (forward_speed, 0.0, 0.0),
            "backward": (-forward_speed, 0.0, 0.0),
            "left": (0.0, MAX_VY, 0.0),
            "right": (0.0, -MAX_VY, 0.0),
            "turn_left": (0.0, 0.0, turn_speed),
            "turn_right": (0.0, 0.0, -turn_speed),
            "turn_left_90": (0.0, 0.0, turn_speed),
            "turn_right_90": (0.0, 0.0, -turn_speed),
            "turn_left_180": (0.0, 0.0, turn_speed),
            "turn_right_180": (0.0, 0.0, -turn_speed),
            "forward_distance": (forward_speed, 0.0, 0.0),
            "backward_distance": (-forward_speed, 0.0, 0.0),
            "wait": (0.0, 0.0, 0.0),
        }
        try:
            while not self._stop_event.is_set():
                for step in path:
                    vx, vy, vyaw = commands[step["action"]]
                    target = step.get("distance")
                    turn_target = FIXED_ANGLES.get(step["action"])
                    start_position = None
                    turn_started = None
                    last_yaw = None
                    turn_progress = 0.0
                    turn_in_tolerance_since = None
                    feedback_active = False
                    if target is not None or turn_target is not None:
                        state = self.state_reader.snapshot()
                        if not state["connected"]:
                            self._set_status("blocked", "机器人状态丢失")
                            return
                        if target is not None:
                            start_position = state["position"]
                        if turn_target is not None:
                            last_yaw = state["imu"]["yaw"]
                            turn_started = time.monotonic()
                    deadline = time.monotonic() + (
                        target / forward_speed + 5.0 if target is not None and forward_speed else
                        5.0 if target is not None else
                        step["duration"] + PATROL_TURN_TIMEOUT_MARGIN
                        if turn_target is not None else
                        step["duration"]
                    )
                    while not self._stop_event.is_set():
                        if time.monotonic() >= deadline:
                            if target is not None:
                                self._set_status("error", "按距离移动超时")
                                return
                            if turn_target is not None and feedback_active:
                                if abs(turn_target - turn_progress) <= PATROL_TURN_SETTLE_TOLERANCE:
                                    break
                                self._set_status(
                                    "error",
                                    "定角转向超时（目标 "
                                    f"{math.degrees(turn_target):.1f}°，实际 "
                                    f"{math.degrees(turn_progress):.1f}°）",
                                )
                                return
                            break
                        state = self.state_reader.snapshot()
                        if not state["connected"]:
                            self._set_status("blocked", "机器人状态丢失")
                            return
                        if target is not None and self._traveled(start_position, state["position"]) >= target:
                            break
                        if turn_target is not None:
                            now = time.monotonic()
                            current_yaw = state["imu"]["yaw"]
                            turn_progress = self._turn_step(turn_progress, current_yaw, last_yaw)
                            last_yaw = current_yaw
                            feedback_active = feedback_active or abs(turn_progress) > 0.03
                            error = turn_target - turn_progress
                            if turn_in_tolerance_since is not None:
                                if now - turn_in_tolerance_since < PATROL_TURN_HOLD_SECONDS:
                                    self._stop_event.wait(PATROL_TURN_CONTROL_INTERVAL)
                                    continue
                                if abs(error) <= PATROL_TURN_SETTLE_TOLERANCE:
                                    break
                                turn_in_tolerance_since = None
                            if abs(error) <= PATROL_TURN_TOLERANCE:
                                self.controller.stop()
                                turn_in_tolerance_since = now
                                self._stop_event.wait(PATROL_TURN_CONTROL_INTERVAL)
                                continue
                            if not feedback_active and now - turn_started >= step["duration"]:
                                break
                            vyaw = math.copysign(
                                min(
                                    turn_speed,
                                    max(PATROL_TURN_MIN_YAW, abs(error) * PATROL_TURN_KP),
                                ),
                                error,
                            )
                        self.controller.move(vx, vy, vyaw)
                        self._stop_event.wait(
                            PATROL_TURN_CONTROL_INTERVAL if turn_target is not None else 0.05
                        )
                    self.controller.stop()
                    self._stop_event.wait(PATROL_SETTLE_SECONDS)
                    if self._stop_event.is_set():
                        break
        except Exception as error:
            log.exception("Patrol failed")
            self._set_status("error", str(error))
        finally:
            try:
                self.controller.stop()
            finally:
                with self._lock:
                    if self._status in {"running", "stopping"}:
                        self._status = "idle"
                        self._reason = ""
                    self._thread = None

    def _set_status(self, status, reason):
        with self._lock:
            self._status = status
            self._reason = reason

    @staticmethod
    def _traveled(start, current):
        return math.hypot(current["x"] - start["x"], current["y"] - start["y"])

    @staticmethod
    def _angle_delta(current, previous):
        return (current - previous + math.pi) % (2 * math.pi) - math.pi

    @classmethod
    def _turn_step(cls, progress, current, previous):
        return progress + cls._angle_delta(current, previous)

