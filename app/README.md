# Go2 Web Control

面向 Ubuntu 20.04 / Python 3.8 的单机器人控制台。保留原装摄像头、DDS 遥测、键盘/摇杆遥控和动作巡逻；已移除 SLAM 地图导航与 D435i。

## 安装与运行

在项目根目录安装并启动：

```bash
make install
make dev
```

`make install` 会创建/复用 `.venv`，安装 `unitree_sdk2py`、应用依赖和测试依赖。
`make dev` 自动查找持有 `192.168.123.x` 地址的网卡：Windows 使用适配器别名
（如 `以太网`、`Ethernet`），Linux/macOS 使用 `eth0`、`en8` 等接口名，换电脑
不需要修改任何名称。需要换用其他网卡时再覆盖：

```bash
IFACE=<网卡名> make dev
```

Windows 原生环境需要 Git Bash 或 MSYS2 提供 `sh`、`make`、`uv`。
机器人 SDK 和 CycloneDDS 建议在 WSL2 中运行，WSL 内按 Linux 方式执行同样的 `make install` / `make dev`。

`make start` 与 `make dev` 等价。

默认监听 `127.0.0.1:8000`。远程使用 SSH 隧道后访问本机 8000 端口：

```bash
ssh -L 8000:127.0.0.1:8000 go2@ROBOT_IP
```

遥控页 `/`，动作巡逻页 `/patrol`。仅在已有访问控制的可信网络中显式设置 `HOST=0.0.0.0 make dev`；应用没有账号认证。
已有环境也可执行 `python3 -m uvicorn app:app --host 127.0.0.1 --port 8000`，兼容 `server:app`；不设置 `GO2_IFACE` 时同样自动检测网卡。
**只运行一个进程，不使用多个 Uvicorn workers 或开发热重载控制实机。**

## 控制行为

- “退出倒立”使用 `/api/handstand/exit`，单独发送 `HandStand(False)`，不紧接 `StopMove`。随后默认等待 3 秒，期间拒绝普通动作和移动；可用 `HANDSTAND_EXIT_SECONDS` 调整为 0.5–15 秒。这是应用等待窗口，不是官方落地时长，也不代表已确认落地。“立即停止”仍保留原停止路径，退出失败保留待停止与 watchdog 重试。
- 官方 SDK 的 `HandStand` 只有布尔开关，没有落地速度参数。参考：https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/go2/sport/sport_client.py 。该调整避免普通退出时叠加停止指令，实际落地效果仍需实机验证。

- 空闲状态点击“起立”直接发送 `StandUp`，不再以前置 `StopMove` 作为条件；存在移动、特殊模式或停止待确认时仍先确认停止，不忽略 `-1`。
- “倒立”调用 `HandStand(True)`，“拜年”调用 `Scrape()`。倒立期间不接受移动；“立即停止”或切换动作会先调用 `HandStand(False)` 退出倒立。动作能力取决于机器人固件支持。
- 所有移动统一受 `MAX_VX/MAX_VY/MAX_VYAW` 服务端硬上限约束；网页保存正数速度档位，首次打开保留默认值。
- 同一浏览器的序号拒绝旧移动请求；持续移动期间拒绝其他浏览器直接覆盖。停止会释放移动控制权，任何操作者均可停止。
- 旧移动请求在停止巡逻前被拒绝。每次服务运行最多记录 128 个控制会话，满额后拒绝新会话移动，但已有会话和停止仍可使用；重启服务可清空记录。不会淘汰旧序号，以免旧移动请求重新生效。
- 控制 POST 拒绝跨来源和表单请求；网页保持同源访问，脚本使用 JSON 请求。反向代理需保留正确的 Host 和协议信息。
- 手动移动同样要求运动遥测新鲜；状态丢失时拒绝移动，并由 watchdog 停止正在进行的移动，停止失败仍保留重试。
- API 模式切换串行执行，巡逻线程未退出时拒绝切换到手动动作。
- 移动超过 0.40 秒未续传时 watchdog 发出停止；SDK 停止失败保留待停止状态并重试，期间拒绝新移动和动作。该超时不是实时停止时延保证，仍受 SDK 调用耗时影响。
- 交叉步立即返回 `code: 0, finish_code: null`，表示已启动；后台在 2 秒后停止，可提前取消，失败由 watchdog 重试。
- `/ws/state` 以 10 Hz 推送机器人与巡逻状态；`/api/video` 输出原装摄像头 MJPEG。
- `/api/health` 的整体就绪要求控制器已初始化且运动状态新鲜；摄像头子状态要求近期收到有效帧。
- SDK `3104` 表示等待 API 应答超时，不等于指令未执行。错误包含具体命令；`/api/health` 的 `control.last_error` 保留最近错误，`control.stop_pending` 表示停止尚未确认。
- `StopMove` 返回 `3104` 时额外发送一次零速度，并立即重试一次 `StopMove`；只有收到成功应答才确认停止。连续超时仍报错并保留待停止状态，由 watchdog 继续重试。起立等动作超时不会自动重放。遥测在线也不证明 sport RPC 响应链路正常。
- `StopMove` 被机器人以 `-1` 拒绝时仍保留待停止状态，但 watchdog 最多每秒重试一次且同一错误只记录一次堆栈。如机器犬处于遥控器姿态或特殊动作状态，先用遥控器切回普通行走状态。

## 音频 API

使用独立 AudioHub 客户端与锁，不与运动 RPC 共用锁。播放单次、不自动重试，不改变音量。
- `GET /api/audio/list`：机器人已上传音频列表。
- `POST /api/audio/upload?name=weather`：请求体为原始 WAV（`Content-Type: audio/wav`），不是 multipart；限 2 MB、60 秒、16 kHz 单声道 16-bit PCM。响应列表中的 `UNIQUE_ID` 用于播放。
- `POST /api/audio/play`：JSON `{"unique_id":"文件 UUID"}`，成功表示播放请求已接受，不是声学出声证明。
- `POST /api/audio/pause`：暂停播放。

```bash
curl -X POST 'http://127.0.0.1:8000/api/audio/upload?name=wuhan-2026-09-12' -H 'Content-Type: audio/wav' --data-binary @audio/wuhan-2026-09-12.wav
curl -X POST http://127.0.0.1:8000/api/audio/play -H 'Content-Type: application/json' -d '{"unique_id":"替换为返回的 UNIQUE_ID"}'
```

示例语音为 2026-09-12 武汉天气预报，不会自动更新日期。来源：[武汉市政府网站 9 月 11 日发布的预报](https://3g.wuhan.gov.cn/hdjl/rdhy/202609/t20260911_2846765.shtml)，9 月 12 日多云间晴天、20–30℃、偏北风 2–3 级。Windows 本地中文 TTS 合成，无新增语音服务依赖。

## 动作巡逻说明

巡逻不再自动避障，不订阅或解析点云，也不需要雷达外参；运动状态中的雷达距离仅供页面显示，不参与控制。
保留手动急停、速度硬上限、移动超时 watchdog，以及机器人状态丢失时停止。
路径由 1–20 步组成并循环运行，原子保存在应用目录的 `patrol_path.json`。
支持定时前后左右移动、原地转向、等待、0.05–20 米距离移动、90°/180°定角转向。
定角转向按 IMU 连续角度闭环纠偏，过冲可反向修正；没有角度变化反馈时按每步校准秒停止。
按距离移动使用起终点平面距离，不是地图规划。

主要硬件校准项（其余见 `config.py`）：

```bash
export MAX_VX=0.50
export MAX_VY=0.40
export MAX_VYAW=1.00
export GO2_RPC_TIMEOUT=1.0
export VIDEO_RPC_TIMEOUT=1.0
export VIDEO_FPS=15
export PATROL_TURN_KP=1.2
export PATROL_TURN_MIN_YAW=0.50
export PATROL_SETTLE_SECONDS=0.50
export PATROL_HEADING_KP=1.5
export PATROL_FORWARD_YAW_TRIM=-0.04
export PATROL_BACKWARD_YAW_TRIM=-0.04
```

## systemd

将应用部署至 `/opt/go2_web`，准备 `go2` 用户及其 SDK/CycloneDDS 环境。按实际路径编辑服务中的环境变量：

```bash
sudo cp go2-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now go2-web
```

## 无硬件测试

### RPC 诊断日志

服务启动后写入 `logs/rpc.log`，单文件 5 MB，保留 3 个轮转备份。
必须同时部署本仓库 SDK 的 `rpc/client_stub.py`、`rpc/client_base.py` 与应用 `app.py`，并重启服务。
仅记录 sport 服务元数据，不记录图像、凭据或完整载荷。
`send_request` / `send_no_reply` 是发送入口，`write ok=True` 只代表 DDS 写入成功；
`wait_failed code=3104` 是等待超时；`response` 包含原始状态码及 `matched`。
同一 `id` 的 `mono_ns` 差值除以 1e6 是毫秒间隔。
超时后收到同一 ID 的 `response matched=False` 可证明迟到应答；
单独出现 `matched=False` 也可能是其他客户端的应答，不能直接归类为迟到。
完全没有应答日志仍不能区分机器人未发送与链路未送达。

在本目录运行，不启动应用硬件生命周期：

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
node --check static/app.js
node tests/test_frontend.cjs
```

单元测试不替代真实机器人上的停止时延和转向校准验证。
