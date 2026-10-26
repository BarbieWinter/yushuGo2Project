# Unitree SDK2 Python 功能清单

> 依据：`unitree_sdk2_python` 仓库 HEAD `814556d`（2026-09-21）
> 生成日期：2026-10-25
> 重点：Go2（本项目实际机型）；其他机型只做清单级说明

---

## 0. 快速导航

- [1. SDK 架构](#1-sdk-架构)
- [2. Go2 高层运动指令（SportClient 全部 38 个）](#2-go2-高层运动指令sportclient-全部-38-个)
- [3. Go2 其他客户端](#3-go2-其他客户端)
- [4. DDS 遥测与底层控制](#4-dds-遥测与底层控制)
- [5. 返回码](#5-返回码)
- [6. 工具模块](#6-工具模块)
- [7. 示例清单](#7-示例清单)
- [8. 其他机型模块](#8-其他机型模块)
- [9. 可直接复制的最小示例](#9-可直接复制的最小示例)
- [10. 注意事项](#10-注意事项)

---

## 1. SDK 架构

SDK 有两条通信路径：

1. **Topic 发布/订阅**：直接收发 DDS 消息，例如 `rt/lowstate`、`rt/lowcmd`、`rt/sportmodestate`。
2. **RPC 请求/响应**：在 DDS 上封装的服务调用，例如 `sport`、`vui`、`robot_state`。每个服务有对应的 `rt/api/<service>/request` 与 `/response`。

入口：

```python
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(0, "en8")   # domain=0, 网卡 en8
```

- 不传网卡名时使用 autodetermine，多网卡机器容易选错。
- 同一进程只初始化一次，重复调用是空操作。
- `ChannelPublisher(topic, MsgType)` + `Init()` + `Write(sample)`
- `ChannelSubscriber(topic, MsgType)` + `Init(handler, queueLen)` 或 `Read(timeout)`

RPC 客户端统一流程：

```python
client = SportClient()
client.SetTimeout(5.0)
client.Init()
code = client.StandUp()
```

---

## 2. Go2 高层运动指令（SportClient 全部 38 个）

服务名：`sport`，API 版本 `1.0.0.1`。

除特别说明外，方法只返回 `code`（0 成功）。所有动作是否可用取决于机器人固件和当前状态。

### 2.1 姿态与站立

| 方法 | API ID | 参数 | 说明 |
|---|---:|---|---|
| `Damp()` | 1001 | 无 | 阻尼/瘫软，关节卸力。站立时调用会直接趴下 |
| `BalanceStand()` | 1002 | 无 | 平衡站立 |
| `StopMove()` | 1003 | 无 | 停止移动 |
| `StandUp()` | 1004 | 无 | 从趴下起立 |
| `StandDown()` | 1005 | 无 | 趴下 |
| `RecoveryStand()` | 1006 | 无 | 跌倒后恢复站立 |
| `Euler(roll, pitch, yaw)` | 1007 | 3 个 float | 设置机身姿态角（单位 rad） |
| `Sit()` | 1009 | 无 | 坐下 |
| `RiseSit()` | 1010 | 无 | 从坐姿起立 |
| `SpeedLevel(level)` | 1015 | int | 速度档位。档位范围以固件为准 |
| `SwitchJoystick(on)` | 1027 | bool | 切换手柄输入 |
| `Pose(flag)` | 1028 | bool | 摆姿势模式开关 |
| `AutoRecoverySet(enabled)` | 2054 | bool | 自动恢复开关 |
| `AutoRecoveryGet()` | 2055 | 无 | 返回 `(code, bool)` |

### 2.2 移动与步态

| 方法 | API ID | 参数 | 说明 |
|---|---:|---|---|
| `Move(vx, vy, vyaw)` | 1008 | 3 个 float | 速度控制。`vx` 前后 m/s，`vy` 左右 m/s，`vyaw` 转向 rad/s |
| `StaticWalk()` | 1061 | 无 | 静态步行 |
| `TrotRun()` | 1062 | 无 | 小跑 |
| `FreeWalk()` | 2045 | 无 | 自由步行 |
| `FreeBound(flag)` | 2046 | bool | 自由弹跳步态开关 |
| `FreeJump(flag)` | 2047 | bool | 自由跳跃开关 |
| `FreeAvoid(flag)` | 2048 | bool | 自由避障开关 |
| `ClassicWalk(flag)` | 2049 | bool | 经典步态开关 |
| `WalkUpright(flag)` | 2050 | bool | 直立行走开关 |
| `CrossStep(flag)` | 2051 | bool | 交叉步开关 |
| `SwitchAvoidMode()` | 2058 | 无 | 切换避障模式 |

`Move` 使用 `_CallNoReply`，返回 0 只代表指令已发出，不代表机器人已执行。需要持续下发，通常 10–50 Hz；停发后机器人可能继续按最后速度运动，必须用 `StopMove` 或速度 0。

`EconomicGait()`（1063）在 C++ SDK 中存在，**Python 版没有封装**。

### 2.3 特技与表演动作

| 方法 | API ID | 参数 | 说明 |
|---|---:|---|---|
| `Hello()` | 1016 | 无 | 打招呼/握手 |
| `Stretch()` | 1017 | 无 | 伸懒腰 |
| `Content()` | 1020 | 无 | 满足/开心动作 |
| `Dance1()` | 1022 | 无 | 舞蹈 1 |
| `Dance2()` | 1023 | 无 | 舞蹈 2 |
| `Scrape()` | 1029 | 无 | 作揖/拜年 |
| `Heart()` | 1036 | 无 | 比心 |
| `FrontFlip()` | 1030 | 无 | 前空翻 |
| `FrontJump()` | 1031 | 无 | 前跳 |
| `FrontPounce()` | 1032 | 无 | 前扑 |
| `LeftFlip()` | 2041 | 无 | 左侧翻 |
| `BackFlip()` | 2043 | 无 | 后空翻 |
| `HandStand(flag)` | 2044 | bool | 倒立开关 |

### 2.4 完整 API ID 对照

```
1001 Damp              1002 BalanceStand       1003 StopMove
1004 StandUp           1005 StandDown          1006 RecoveryStand
1007 Euler             1008 Move               1009 Sit
1010 RiseSit           1015 SpeedLevel         1016 Hello
1017 Stretch           1020 Content            1022 Dance1
1023 Dance2            1027 SwitchJoystick     1028 Pose
1029 Scrape            1030 FrontFlip          1031 FrontJump
1032 FrontPounce       1036 Heart              1061 StaticWalk
1062 TrotRun           1063 EconomicGait*      2041 LeftFlip
2043 BackFlip          2044 HandStand          2045 FreeWalk
2046 FreeBound         2047 FreeJump           2048 FreeAvoid
2049 ClassicWalk       2050 WalkUpright        2051 CrossStep
2054 AutoRecoverySet   2055 AutoRecoveryGet    2058 SwitchAvoidMode
```

`*` 1063 仅 C++ SDK 提供。

---

## 3. Go2 其他客户端

### 3.1 ObstaclesAvoidClient（避障）

服务名：`obstacles_avoid`，API 版本 `1.0.0.2`。

| 方法 | API ID | 参数 | 说明 |
|---|---:|---|---|
| `SwitchSet(on)` | 1001 | bool | 开/关避障 |
| `SwitchGet()` | 1002 | 无 | 返回 `(code, enable)` |
| `Move(vx, vy, vyaw)` | 1003 | 3 个 float | 速度模式（mode=0），无回复 |
| `MoveToIncrementPosition(x, y, yaw)` | 1003 | 3 个 float | 增量位置（mode=1），无回复 |
| `MoveToAbsolutePosition(x, y, yaw)` | 1003 | 3 个 float | 绝对位置（mode=2），无回复 |
| `UseRemoteCommandFromApi(flag)` | 1004 | bool | 是否使用 API 作为遥控输入 |

### 3.2 VideoClient（前置相机）

服务名：`videohub`，API 版本 `1.0.0.1`。

| 方法 | API ID | 返回 | 说明 |
|---|---:|---|---|
| `GetImageSample()` | 1001 | `(code, bytes list)` | 单帧 JPEG |

示例：`example/go2/front_camera/capture_image.py`、`camera_opencv.py`。

### 3.3 VuiClient（灯效、音量、开关）

服务名：`vui`，API 版本 `1.0.0.1`。

| 方法 | API ID | 参数 | 返回 |
|---|---:|---|---|
| `SetSwitch(enable)` | 1001 | int | code |
| `GetSwitch()` | 1002 | 无 | `(code, enable)` |
| `SetVolume(level)` | 1003 | int | code |
| `GetVolume()` | 1004 | 无 | `(code, level)` |
| `SetBrightness(level)` | 1005 | int | code |
| `GetBrightness()` | 1006 | 无 | `(code, level)` |

### 3.4 RobotStateClient（服务管理）

服务名：`robot_state`，API 版本 `1.0.0.1`。

| 方法 | API ID | 参数 | 返回 |
|---|---:|---|---|
| `ServiceList()` | 1003 | 无 | `(code, [ServiceState])` |
| `ServiceSwitch(name, switch)` | 1001 | str, bool | code |
| `SetReportFreq(interval, duration)` | 1002 | int, int | code |

`ServiceState` 字段：`name`、`status`、`protect`。

错误码：

- `5201`：服务切换失败
- `5202`：服务受保护，禁止切换

### 3.5 MotionSwitcherClient（模式切换）

服务名：`motion_switcher`，API 版本 `1.0.0.1`。

| 方法 | API ID | 参数 | 返回 |
|---|---:|---|---|
| `CheckMode()` | 1001 | 无 | `(code, dict)`，`dict["name"]` 为当前模式 |
| `SelectMode(name)` | 1002 | str | code |
| `ReleaseMode()` | 1003 | 无 | code |

常见模式名（见官方示例）：`normal`、`ai`、`advanced`、`ai-w`（轮式）。

`SetSilent` / `GetSilent` 的 API ID（1004/1005）在头文件里存在，但 Python 客户端没有封装对应方法。

跑底层 `rt/lowcmd` 前，官方示例先 `CheckMode()`，再 `ReleaseMode()` 释放当前运动服务，而不是用 `SelectMode("lowlevel")`。

---

## 4. DDS 遥测与底层控制

### 4.1 Topic 一览

| Topic | 方向 | 消息类型 | 用途 |
|---|---|---|---|
| `rt/lowstate` | 机器人 → PC | `LowState_` | 电机、IMU、电池、足端力、温度、遥控器 |
| `rt/sportmodestate` | 机器人 → PC | `SportModeState_` | 运动模式、机身高度、速度、错误码 |
| `rt/lowcmd` | PC → 机器人 | `LowCmd_` | 12 关节底层控制 |
| `rt/utlidar/switch` | PC → 机器人 | `std_msgs/String` | 雷达开关，值为 `"ON"` / `"OFF"` |
| `rt/wirelesscontroller` | 双向 | `WirelessController_` | 遥控器摇杆/按键 |
| `rt/secondary_imu` | 机器人 → PC | `IMUState_` | 第二 IMU（部分机型） |
| `rt/lf/lowstate` | 机器人 → PC | `LowState_` | 低频率状态（部分机型） |
| `rt/lf/sportmodestate` | 机器人 → PC | `SportModeState_` | 低频率运动状态（部分机型） |
| `rt/arm_sdk` | 双向 | 机械臂消息 | 人形机械臂（G1/H1/H2） |

RPC 示例：

```
rt/api/sport/request           rt/api/sport/response
rt/api/vui/request             rt/api/vui/response
rt/api/robot_state/request     rt/api/robot_state/response
rt/api/obstacles_avoid/request rt/api/obstacles_avoid/response
rt/api/motion_switcher/request rt/api/motion_switcher/response
```

### 4.2 LowState_ 字段

```
head[2], level_flag, frame_reserve, sn[2], version[2], bandwidth
imu_state
motor_state[20]
bms_state
foot_force[4], foot_force_est[4]
tick, wireless_remote[40], bit_flag
adc_reel
temperature_ntc1, temperature_ntc2
power_v, power_a
fan_frequency[4]
reserve, crc
```

`MotorState_`：

```
mode, q, dq, ddq, tau_est
q_raw, dq_raw, ddq_raw
temperature, lost, reserve[2]
```

`IMUState_`：

```
quaternion[4], gyroscope[3], accelerometer[3], rpy[3], temperature
```

`BmsState_`：

```
version_high, version_low, status, soc, current, cycle
bq_ntc[2], mcu_ntc[2], cell_vol[15]
```

`SportModeState_`：

```
stamp, error_code, imu_state, mode, progress, gait_type
foot_raise_height, position[3], body_height, velocity[3], yaw_speed
range_obstacle[4], foot_force[4]
foot_position_body[12], foot_speed_body[12]
path_point[10]
```

Go2 的 IMU 温度常驻在 79°C 左右，属于正常现象，不要拿它做超温报警。

### 4.3 底层控制 LowCmd_

`LowCmd_` 字段：

```
head[2], level_flag, frame_reserve, sn[2], version[2], bandwidth
motor_cmd[20]
bms_cmd
wireless_remote[40]
led[12], fan[2], gpio
reserve, crc
```

`MotorCmd_`：

```
mode, q, dq, tau, kp, kd, reserve[3]
```

Go2 的 12 个有效关节：

| 索引 | 名称 | 含义 |
|---:|---|---|
| 0 | `FR_0` | 右前髋 |
| 1 | `FR_1` | 右前大腿 |
| 2 | `FR_2` | 右前小腿 |
| 3 | `FL_0` | 左前髋 |
| 4 | `FL_1` | 左前大腿 |
| 5 | `FL_2` | 左前小腿 |
| 6 | `RR_0` | 右后髋 |
| 7 | `RR_1` | 右后大腿 |
| 8 | `RR_2` | 右后小腿 |
| 9 | `RL_0` | 左后髋 |
| 10 | `RL_1` | 左后大腿 |
| 11 | `RL_2` | 左后小腿 |

底层控制要求（参考 `example/go2/low_level/go2_stand_example.py`）：

- 控制周期通常 2 ms（500 Hz），范围 1–10 ms
- 每帧必须计算 CRC
- `motor_cmd[i].mode = 0x01`
- 默认 `Kp=60`、`Kd=5` 只是示例值，实机需重新调
- 进入前先用 `MotionSwitcherClient.ReleaseMode()` 退出 sport 服务
- 失能时用 `PosStopF = 2.146e9`、`VelStopF = 16000.0`
- 误用可能导致机器人失稳，必须先吊起或放在安全支架上

### 4.4 IDL 消息（24 个）

```
AudioData_       BmsCmd_          BmsState_        Error_
Go2FrontVideoData_  HeightMap_    IMUState_        InterfaceConfig_
LidarState_      LowCmd_          LowState_        MotorCmd_
MotorCmds_       MotorState_      MotorStates_     PathPoint_
Req_             Res_             SportModeState_  TimeSpec_
UwbState_        UwbSwitch_       WirelessController_
```

`unitree_sdk2py.idl.default` 提供对应的构造 helper，例如：

```python
from unitree_sdk2py.idl.default import unitree_go_msg_dds__LowCmd_
cmd = unitree_go_msg_dds__LowCmd_()
```

---

## 5. 返回码

### 5.1 RPC 通用码

| 码 | 含义 |
|---:|---|
| 0 | 成功 |
| 3001 | 未知错误 |
| 3102 | 客户端发送失败（主题没有匹配的订阅者/服务未运行） |
| 3103 | 客户端调用未注册的 API |
| 3104 | 等待服务端应答超时 |
| 3105 | 请求/应答 API 不匹配 |
| 3106 | 数据错误 |
| 3107 | lease 无效 |
| 3201 | 服务端发送失败 |
| 3202 | 服务端内部错误 |
| 3203 | 服务端未实现该 API |
| 3204 | 参数错误 |
| 3205 | lease 被拒绝 |
| 3206 | lease 不存在 |
| 3207 | lease 已存在 |

### 5.2 Sport 专用

| 码 | 含义 |
|---:|---|
| 4101 | 路径点错误 |
| 4201 | 服务端超时 |
| 4202 | 服务端未初始化 |

### 5.3 常见现象

- `3102`：服务没起来、网卡/DDS 没通，或机器人当前模式没有该服务
- `3104`：请求发出去了，但没等到应答；**不代表指令没执行**
- `-1`：服务端明确拒绝，通常是当前姿态/模式不允许该动作

---

## 6. 工具模块

| 模块 | 功能 |
|---|---|
| `unitree_sdk2py.utils.crc.CRC` | 计算/校验 LowCmd 的 CRC |
| `unitree_sdk2py.utils.joystick.Joystick` | 解析遥控器按键、摇杆，依赖 pygame |
| `unitree_sdk2py.utils.thread.RecurrentThread` | 固定周期后台线程 |
| `unitree_sdk2py.utils.bqueue.BQueue` | 阻塞队列 |
| `unitree_sdk2py.utils.hz_sample.HzSample` | 频率统计 |
| `unitree_sdk2py.utils.timerfd.TimerFD` | 定时器文件描述符 |
| `unitree_sdk2py.utils.singleton.Singleton` | 单例基类 |
| `unitree_sdk2py.utils.clib_lookup` | 动态库查找 |

---

## 7. 示例清单

`example/` 共 53 个脚本。

### 7.1 Go2 示例（6 个）

| 文件 | 内容 |
|---|---|
| `go2/high_level/go2_sport_client.py` | 交互式菜单，覆盖全部运动指令 |
| `go2/high_level/go2_utlidar_switch.py` | 雷达 `ON`/`OFF` |
| `go2/low_level/go2_stand_example.py` | `rt/lowcmd` 底层站立、CRC、500 Hz |
| `go2/low_level/unitree_legged_const.py` | 12 关节索引、模式常量 |
| `go2/front_camera/camera_opencv.py` | 相机 + OpenCV 显示 |
| `go2/front_camera/capture_image.py` | 抓取单帧 JPEG |

### 7.2 通用示例

| 文件 | 内容 |
|---|---|
| `helloworld/publisher.py` / `subscriber.py` | 最小 DDS 发布订阅 |
| `motionSwitcher/motion_switcher_example.py` | normal / ai / advanced / ai-w 模式切换 |
| `obstacles_avoid/obstacles_avoid_switch.py` | 避障开关 |
| `obstacles_avoid/obstacles_avoid_move.py` | 避障移动、绝对/增量位置 |
| `vui_client/vui_client_example.py` | 音量、亮度 |
| `wireless_controller/wireless_controller.py` | 遥控器按键/摇杆 |

### 7.3 其他机型示例

```
a2/ (5)   as2/ (2)   b2/ (5)   b2w/ (5)   g1/ (8)
go2w/ (3) h1/ (3)    h1_2/ (1) h2/ (3)    r1/ (4)
```

---

## 8. 其他机型模块

| 目录 | 主要客户端 | 方法数 | 备注 |
|---|---|---:|---|
> 方法数只统计业务指令，不含 `__init__` / `Init`。

| 目录 | 主要客户端 | 方法数 | 备注 |
|---|---|---:|---|
| `a2` | `SportClient`、`AudioClient` | 20、6 | 轮足/双足，支持 `SwitchGait`、`BodyHeight`、TTS |
| `as2` | `SportClient` | 21 | 与 A2 类似 |
| `b2` | `SportClient`、前后 `VideoClient`、`RobotStateClient`、`VuiClient` | 21、1、1、6、6 | 支持 `TrajectoryFollow`、`VisionWalk` |
| `g1` | `LocoClient`、`ArmActionClient`、`AudioClient` | 23、2、6 | 人形：FSM、手臂动作、TTS |
| `h1` | `LocoClient` | 11 | 人形运动 |
| `h2` | `LocoClient` | 34 | 人形 + 手臂 SDK、BalanceStand、Punch API |
| `r1` | `LocoClient` | 13 | 人形，Run 使用 FSM 811 |

`b2w`、`go2w` 只有示例目录，没有独立 Python 包。

---

## 9. 可直接复制的最小示例

### 9.1 初始化 + 起立

```python
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.go2.sport.sport_client import SportClient

ChannelFactoryInitialize(0, "en8")

sport = SportClient()
sport.SetTimeout(5.0)
sport.Init()

print("StandUp:", sport.StandUp())
```

### 9.2 前后左右移动

```python
import time
from unitree_sdk2py.go2.sport.sport_client import SportClient

sport.Move(0.3, 0.0, 0.0)   # 前进 0.3 m/s
time.sleep(1.0)
sport.Move(0.0, 0.0, 0.0)   # 停止
sport.StopMove()
```

### 9.3 动作

```python
sport.Hello()
sport.Stretch()
sport.Dance1()
sport.Heart()
sport.FrontJump()
sport.BackFlip()
sport.HandStand(True)
sport.HandStand(False)
```

### 9.4 读取状态

```python
import time
from unitree_sdk2py.core.channel import ChannelSubscriber
from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_, SportModeState_

box = {}
low = ChannelSubscriber("rt/lowstate", LowState_)
low.Init(lambda m: box.__setitem__("low", m), 10)
sport_state = ChannelSubscriber("rt/sportmodestate", SportModeState_)
sport_state.Init(lambda m: box.__setitem__("sport", m), 10)

time.sleep(1)
print(box["low"].bms_state.soc, box["sport"].body_height)
```

### 9.5 相机取帧

```python
from unitree_sdk2py.go2.video.video_client import VideoClient

video = VideoClient()
video.SetTimeout(5.0)
video.Init()
code, data = video.GetImageSample()
if code == 0:
    open("frame.jpg", "wb").write(bytes(data))
```

### 9.6 音量/亮度

```python
from unitree_sdk2py.go2.vui.vui_client import VuiClient

vui = VuiClient()
vui.SetTimeout(5.0)
vui.Init()
vui.SetVolume(5)
vui.SetBrightness(5)
```

### 9.7 服务列表

```python
from unitree_sdk2py.go2.robot_state.robot_state_client import RobotStateClient

rs = RobotStateClient()
rs.SetTimeout(5.0)
rs.Init()
code, services = rs.ServiceList()
for s in services or []:
    print(s.name, s.status, s.protect)
```

---

## 10. 注意事项

1. **服务未启动时返回 3102。** 例如机器人运动控制程序没跑，`SportClient` 所有调用都会失败。
2. **`Move` 无应答。** 返回 0 只代表 DDS 写成功，不能当作执行成功。
3. **移动必须持续下发。** 停发后机器人可能保持最后速度；退出前一定要 `StopMove()`。
4. **不同固件支持的动作不同。** 调用失败返回 `-1` 或 `4201` 很常见，不代表 SDK 有问题。
5. **底层 `rt/lowcmd` 风险最高。** 需要 CRC、500 Hz、正确关节索引和增益；错误指令可能让机器人失稳。
6. **多网卡必须指定接口。** 否则 DDS 可能选错网卡；表现为收不到任何 topic。
7. **IMU 温度 79°C 是常态。** 电机温度、电池 NTC 才有参考价值。
8. **`error_code` 不能可靠判断姿态。** 用 `SportModeState.body_height` 判断站立/趴下更稳。
9. **`3104` 不等于失败。** 它表示没等到应答，指令可能已执行；需要结合机器人实际状态判断。
10. **当前（2026-10-25）实机 `sport` 服务未运行。** 现场调用返回 `3102`，需先让机器人运动服务恢复。

---

## 附：文件位置

```
unitree_sdk2_python/
├── unitree_sdk2py/
│   ├── core/channel.py                  DDS 初始化、发布、订阅
│   ├── rpc/client.py                    RPC 客户端基类
│   ├── go2/sport/sport_client.py        Go2 运动指令
│   ├── go2/video/video_client.py        前置相机
│   ├── go2/vui/vui_client.py            灯效/音量
│   ├── go2/robot_state/robot_state_client.py  服务管理
│   ├── go2/obstacles_avoid/obstacles_avoid_client.py  避障
│   ├── comm/motion_switcher/motion_switcher_client.py 模式切换
│   ├── idl/unitree_go/msg/dds_/         24 个消息定义
│   ├── idl/default.py                   消息默认构造
│   └── utils/                           CRC、线程、队列、手柄
└── example/                             53 个示例
```
