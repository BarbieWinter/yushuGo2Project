import math
import os

from netiface import detect_robot_iface


# GO2_IFACE 显式设置时优先使用；否则自动查找机器人网段的网卡，仍找不到则为
# None，由 CycloneDDS 自行选择。换电脑不需要改网卡名。
GO2_IFACE = detect_robot_iface()
MAX_VX = max(0.05, float(os.getenv("MAX_VX", "0.50")))
MAX_VY = max(0.05, float(os.getenv("MAX_VY", "0.40")))
MAX_VYAW = max(0.05, float(os.getenv("MAX_VYAW", "1.00")))
MIN_WALK_BODY_HEIGHT = float(os.getenv("MIN_WALK_BODY_HEIGHT", "0.12"))
WATCHDOG_TIMEOUT = 0.40
HANDSTAND_EXIT_SECONDS = float(os.getenv("HANDSTAND_EXIT_SECONDS", "3.0"))
if not math.isfinite(HANDSTAND_EXIT_SECONDS) or not 0.5 <= HANDSTAND_EXIT_SECONDS <= 15:
    raise ValueError("HANDSTAND_EXIT_SECONDS must be between 0.5 and 15 seconds")
GO2_RPC_TIMEOUT = max(0.1, float(os.getenv("GO2_RPC_TIMEOUT", "1.0")))
VIDEO_RPC_TIMEOUT = max(0.2, float(os.getenv("VIDEO_RPC_TIMEOUT", "1.0")))
VIDEO_FPS = max(1.0, float(os.getenv("VIDEO_FPS", "15")))

PATROL_FORWARD_SECONDS = 4.0
PATROL_TURN_SECONDS = float(
    os.getenv("PATROL_TURN_SECONDS", str(math.pi / (2 * MAX_VYAW)))
)
PATROL_TURN_TOLERANCE = float(os.getenv("PATROL_TURN_TOLERANCE", "0.010"))
PATROL_TURN_SETTLE_TOLERANCE = float(
    os.getenv("PATROL_TURN_SETTLE_TOLERANCE", "0.020")
)
PATROL_TURN_KP = max(0.1, float(os.getenv("PATROL_TURN_KP", "1.2")))
PATROL_TURN_MIN_YAW = max(0.0, float(os.getenv("PATROL_TURN_MIN_YAW", "0.50")))
PATROL_TURN_HOLD_SECONDS = max(
    0.05, float(os.getenv("PATROL_TURN_HOLD_SECONDS", "0.30"))
)
PATROL_TURN_CONTROL_INTERVAL = max(
    0.005, float(os.getenv("PATROL_TURN_CONTROL_INTERVAL", "0.02"))
)
PATROL_TURN_TIMEOUT_MARGIN = max(
    1.0, float(os.getenv("PATROL_TURN_TIMEOUT_MARGIN", "5.0"))
)
PATROL_SETTLE_SECONDS = float(os.getenv("PATROL_SETTLE_SECONDS", "0.50"))
PATROL_HEADING_KP = float(os.getenv("PATROL_HEADING_KP", "1.5"))
PATROL_HEADING_MAX_YAW = float(os.getenv("PATROL_HEADING_MAX_YAW", "0.30"))
PATROL_ODOM_KP = float(os.getenv("PATROL_ODOM_KP", "0.8"))
PATROL_ODOM_MAX_YAW = float(os.getenv("PATROL_ODOM_MAX_YAW", "0.20"))
PATROL_FORWARD_YAW_TRIM = float(os.getenv("PATROL_FORWARD_YAW_TRIM", "-0.04"))
PATROL_BACKWARD_YAW_TRIM = float(os.getenv("PATROL_BACKWARD_YAW_TRIM", "-0.04"))
PATROL_JOIN_TIMEOUT = max(0.1, float(os.getenv("PATROL_JOIN_TIMEOUT", "2.0")))
