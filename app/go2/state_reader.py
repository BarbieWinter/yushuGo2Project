import threading
import time


class Go2StateReader:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._last_update = float("-inf")
        self._sport_subscriber = None
        self._low_subscriber = None
        self._state = self._empty_state()

    def start(self) -> None:
        if self._sport_subscriber is not None:
            return

        from unitree_sdk2py.core.channel import ChannelSubscriber
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_, SportModeState_

        self._sport_subscriber = ChannelSubscriber("rt/sportmodestate", SportModeState_)
        self._low_subscriber = ChannelSubscriber("rt/lowstate", LowState_)
        self._sport_subscriber.Init(self._on_sport, 1)
        self._low_subscriber.Init(self._on_low, 1)

    def stop(self) -> None:
        if self._sport_subscriber is not None:
            self._sport_subscriber.Close()
            self._sport_subscriber = None
        if self._low_subscriber is not None:
            self._low_subscriber.Close()
            self._low_subscriber = None
        with self._lock:
            self._last_update = float("-inf")

    def snapshot(self) -> dict:
        with self._lock:
            state = self._copy_state(self._state)
            state["connected"] = self._clock() - self._last_update < 1.0
            return state

    def _on_sport(self, msg) -> None:
        with self._lock:
            self._state.update(
                {
                    "mode": int(msg.mode),
                    "gait_type": int(msg.gait_type),
                    "position": self._xyz(msg.position),
                    "velocity": self._velocity(msg.velocity),
                    "yaw_speed": float(msg.yaw_speed),
                    "body_height": float(msg.body_height),
                    "imu": self._rpy(msg.imu_state.rpy),
                    "range_obstacle": [float(value) for value in msg.range_obstacle],
                    "foot_force": [int(value) for value in msg.foot_force],
                }
            )
            self._last_update = self._clock()

    def _on_low(self, msg) -> None:
        with self._lock:
            self._state["battery"] = int(msg.bms_state.soc)
            self._state["motor_temperature"] = [
                int(motor.temperature) for motor in msg.motor_state[:12]
            ]

    @staticmethod
    def _empty_state() -> dict:
        return {
            "connected": False,
            "mode": 0,
            "gait_type": 0,
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
            "yaw_speed": 0.0,
            "body_height": 0.0,
            "imu": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            "battery": None,
            "range_obstacle": [0.0, 0.0, 0.0, 0.0],
            "foot_force": [0, 0, 0, 0],
            "motor_temperature": [],
        }

    @staticmethod
    def _xyz(values) -> dict:
        return {"x": float(values[0]), "y": float(values[1]), "z": float(values[2])}

    @staticmethod
    def _velocity(values) -> dict:
        return {"vx": float(values[0]), "vy": float(values[1]), "vz": float(values[2])}

    @staticmethod
    def _rpy(values) -> dict:
        return {"roll": float(values[0]), "pitch": float(values[1]), "yaw": float(values[2])}

    @staticmethod
    def _copy_state(state: dict) -> dict:
        return {
            key: value.copy() if isinstance(value, (dict, list)) else value
            for key, value in state.items()
        }
