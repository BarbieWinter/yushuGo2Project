const $ = (selector) => document.querySelector(selector);
const commandStatus = $("#command-status");
const camera = $("#camera");
const cameraStatus = $("#camera-status");
const connectionDot = $("#connection-dot");
const connectionText = $("#connection-text");
const controlPage = location.pathname === "/";
const patrolPage = location.pathname === "/patrol";
const settingsPage = location.pathname === "/settings";
let activeCameraName = "原装摄像头";

if (controlPage) camera.src = "/api/video";

const profiles = {
  slow: { vx: 0.30, vy: 0.30, vyaw: 0.50 },
  normal: { vx: 0.50, vy: 0.40, vyaw: 1.00 },
};
let profile = profiles.normal;
let moveGeneration = 0;
let moveLoopRunning = false;
let suppressRefresh = false;
let patrolRunning = false;
let moveInput = { vx: 0, vy: 0 };
let yawInput = 0;
const pressedKeys = new Set();
const controlClientId = crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
let controlSequence = 0;

function controlToken() {
  return { client_id: controlClientId, sequence: ++controlSequence };
}

async function post(url, body, quiet = false) {
  const options = { method: "POST", headers: { "Content-Type": "application/json" } };
  if (body !== undefined) options.body = JSON.stringify(body);
  try {
    const response = await fetch(url, options);
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
    if (!response.ok) throw new Error(data.detail || response.statusText);
    if (data.accepted === false) throw new Error("控制请求已过期或机器人正由其他操作控制");
    if (data.code != null && data.code !== 0) throw new Error(`SDK code ${data.code}`);
    if (!quiet) commandStatus.textContent = `${data.command} · code ${data.code}`;
    return data;
  } catch (error) {
    commandStatus.textContent = `请求失败 · ${error.message}`;
    return null;
  }
}

function clamp(value) {
  return Math.max(-1, Math.min(1, value));
}

function deadzone(value) {
  return Math.abs(value) < 0.08 ? 0 : value;
}

function keyboardInput() {
  return {
    vx: Number(pressedKeys.has("KeyW")) - Number(pressedKeys.has("KeyS")),
    vy: Number(pressedKeys.has("KeyA")) - Number(pressedKeys.has("KeyD")),
    vyaw: Number(pressedKeys.has("KeyQ")) - Number(pressedKeys.has("KeyE")),
  };
}

function currentCommand() {
  const keys = keyboardInput();
  return {
    vx: clamp(moveInput.vx + keys.vx) * profile.vx,
    vy: clamp(moveInput.vy + keys.vy) * profile.vy,
    vyaw: clamp(yawInput + keys.vyaw) * profile.vyaw,
  };
}

function inputActive() {
  return moveJoystick.active() || yawJoystick.active() || keyboardInput().vx ||
    keyboardInput().vy || keyboardInput().vyaw;
}

function updatePatrolButton() {
  const button = $("#remote-patrol-toggle");
  button.textContent = patrolRunning ? "停止巡逻" : "开始巡逻";
  button.classList.toggle("running", patrolRunning);
}

async function sendMove() {
  const command = currentCommand();
  $("#move-output").textContent = `vx ${command.vx.toFixed(2)} · vy ${command.vy.toFixed(2)}`;
  $("#yaw-output").textContent = `yaw ${command.vyaw.toFixed(2)}`;
  return post("/api/move", { ...command, ...controlToken() }, true);
}

function refreshMoveLoop() {
  if (handstandExiting) return;
  if (inputActive()) {
    patrolRunning = false;
    updatePatrolButton();
    if (!moveLoopRunning) void runMoveLoop(moveGeneration);
  } else {
    stopMoveLoop();
    sendStop(true);
  }
}

async function runMoveLoop(generation) {
  moveLoopRunning = true;
  while (generation === moveGeneration && inputActive()) {
    const started = performance.now();
    await sendMove();
    const delay = 50 - (performance.now() - started);
    if (delay > 0) await new Promise((resolve) => window.setTimeout(resolve, delay));
  }
  if (generation === moveGeneration) moveLoopRunning = false;
}

function stopMoveLoop() {
  moveGeneration += 1;
  moveLoopRunning = false;
}

function sendStop(quiet = false) {
  return post("/api/stop", controlToken(), quiet);
}

function hardStop(send = true) {
  patrolRunning = false;
  updatePatrolButton();
  stopMoveLoop();
  pressedKeys.clear();
  suppressRefresh = true;
  moveJoystick.reset();
  yawJoystick.reset();
  suppressRefresh = false;
  moveInput = { vx: 0, vy: 0 };
  yawInput = 0;
  $("#move-output").textContent = "vx 0.00 · vy 0.00";
  $("#yaw-output").textContent = "yaw 0.00";
  return send ? sendStop() : true;
}

function createJoystick(selector, onChange, horizontalOnly = false) {
  const root = $(selector);
  const knob = root.querySelector(".joystick-knob");
  let pointerId = null;

  function update(event) {
    const rect = root.getBoundingClientRect();
    const radius = rect.width * 0.34;
    let x = clamp((event.clientX - rect.left - rect.width / 2) / radius);
    let y = horizontalOnly ? 0 : clamp((event.clientY - rect.top - rect.height / 2) / radius);
    if (!horizontalOnly && Math.hypot(x, y) > 1) {
      const length = Math.hypot(x, y);
      x /= length;
      y /= length;
    }
    x = deadzone(x);
    y = deadzone(y);
    knob.style.transform = `translate(${x * radius}px, ${y * radius}px)`;
    onChange(x, y);
    refreshMoveLoop();
  }

  function release(event) {
    if (event && (pointerId === null || event.pointerId !== pointerId)) return;
    pointerId = null;
    knob.style.transform = "";
    onChange(0, 0);
    if (!suppressRefresh) refreshMoveLoop();
  }

  root.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    pointerId = event.pointerId;
    root.setPointerCapture(pointerId);
    update(event);
  });
  root.addEventListener("pointermove", (event) => {
    if (event.pointerId === pointerId) update(event);
  });
  ["pointerup", "pointerleave", "pointercancel", "lostpointercapture"].forEach((name) =>
    root.addEventListener(name, release),
  );

  return {
    active: () => pointerId !== null,
    reset: () => release(),
  };
}

const moveJoystick = createJoystick("#move-joystick", (x, y) => {
  moveInput = { vx: -y, vy: -x };
});
const yawJoystick = createJoystick("#yaw-joystick", (x) => {
  yawInput = -x;
}, true);

document.querySelectorAll("[data-speed]").forEach((button) => {
  button.addEventListener("click", () => {
    profile = profiles[button.dataset.speed];
    document.querySelectorAll("[data-speed]").forEach((item) => item.classList.remove("selected"));
    button.classList.add("selected");
    if (inputActive()) sendMove();
  });
});

const normalSpeedInputs = { vx: $("#normal-vx"), vyaw: $("#normal-vyaw") };
for (const [key, input] of Object.entries(normalSpeedInputs)) {
  let saved = null;
  try { saved = localStorage.getItem(`go2-normal-${key}`); } catch {}
  const speed = saved === null ? NaN : Number(saved);
  if (Number.isFinite(speed) && speed > 0) input.value = speed;
  profiles.normal[key] = input.valueAsNumber;
}

function saveNormalSpeed() {
  if (!Object.values(normalSpeedInputs).every((input) => input.reportValidity())) return;
  try {
    for (const [key, input] of Object.entries(normalSpeedInputs)) {
      profiles.normal[key] = input.valueAsNumber;
      localStorage.setItem(`go2-normal-${key}`, input.value);
    }
  } catch {
    $("#speed-save-status").textContent = "保存失败：浏览器禁止本地存储";
    return;
  }
  $("#normal-speed-label").textContent = `${profiles.normal.vx.toFixed(2)} m/s`;
  $("#speed-save-status").textContent = "已保存";
  if (profile === profiles.normal && inputActive()) sendMove();
}

$("#normal-speed-label").textContent = `${profiles.normal.vx.toFixed(2)} m/s`;
$("#speed-settings").addEventListener("submit", (event) => {
  event.preventDefault();
  saveNormalSpeed();
});

const audioStatus = $("#audio-status");
const audioList = $("#audio-list");
const audioFile = $("#audio-file");
const audioName = $("#audio-name");
const volume = $("#speaker-volume");

function apiDetail(data, fallback) {
  if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg).join("；");
  return data.detail || fallback;
}

async function audioRequest(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(apiDetail(data, response.statusText));
  return data;
}

function renderAudioList(items) {
  audioList.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "audio-empty";
    empty.textContent = "尚未上传音频";
    audioList.append(empty);
    return;
  }
  for (const item of items) {
    const row = document.createElement("li");
    row.className = "audio-item";
    const info = document.createElement("div");
    info.className = "audio-info";
    const name = document.createElement("strong");
    name.textContent = item.CUSTOM_NAME;
    const meta = document.createElement("span");
    const duration = Number.isFinite(item.DURATION) ? `${item.DURATION.toFixed(1)} 秒` : "时长未知";
    const size = Number.isFinite(item.SIZE) ? `${(item.SIZE / 1024).toFixed(0)} KB` : "";
    meta.textContent = [duration, size, new Date(item.ADD_TIME).toLocaleString()].filter(Boolean).join(" · ");
    info.append(name, meta);

    const actions = document.createElement("div");
    actions.className = "audio-actions";
    const play = document.createElement("button");
    play.type = "button";
    play.textContent = "播放";
    play.addEventListener("click", async () => {
      play.disabled = true;
      audioStatus.textContent = `正在准备「${item.CUSTOM_NAME}」…`;
      try {
        await audioRequest("/api/audio/play", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ unique_id: item.UNIQUE_ID }),
        });
        audioStatus.textContent = `已提交「${item.CUSTOM_NAME}」；长音频需要先传输到扬声器。`;
      } catch (error) {
        audioStatus.textContent = `播放失败 · ${error.message}`;
      } finally {
        play.disabled = false;
      }
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete-audio";
    remove.textContent = "删除";
    remove.addEventListener("click", async () => {
      if (!confirm(`删除音频「${item.CUSTOM_NAME}」？`)) return;
      remove.disabled = true;
      try {
        await audioRequest(`/api/audio/${item.UNIQUE_ID}`, { method: "DELETE" });
        audioStatus.textContent = `已删除「${item.CUSTOM_NAME}」`;
        await loadAudioList();
      } catch (error) {
        audioStatus.textContent = `删除失败 · ${error.message}`;
        remove.disabled = false;
      }
    });
    actions.append(play, remove);
    row.append(info, actions);
    audioList.append(row);
  }
}

async function loadAudioList() {
  audioStatus.textContent = "正在读取音频列表…";
  try {
    const data = await audioRequest("/api/audio/list");
    renderAudioList(data.audio_list || []);
    audioStatus.textContent = `共 ${data.audio_list?.length || 0} 个音频`;
  } catch (error) {
    audioStatus.textContent = `读取失败 · ${error.message}`;
  }
}

audioFile.addEventListener("change", () => {
  if (audioFile.files[0] && !audioName.value.trim()) {
    audioName.value = audioFile.files[0].name.replace(/\.wav$/i, "")
      .replace(/[^\w\u4e00-\u9fff-]+/g, "-").slice(0, 64);
  }
});

$("#audio-upload").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = audioFile.files[0];
  const name = audioName.value.trim();
  if (!file || !name || !event.currentTarget.reportValidity()) return;
  if (file.size > 2_000_000) {
    audioStatus.textContent = "上传失败 · 文件不能超过 2 MB";
    return;
  }
  const button = $("#upload-audio");
  button.disabled = true;
  audioStatus.textContent = "上传中…";
  try {
    const data = await audioRequest(`/api/audio/upload?name=${encodeURIComponent(name)}`, {
      method: "POST", headers: { "Content-Type": "audio/wav" }, body: file,
    });
    renderAudioList(data.audio_list || []);
    event.currentTarget.reset();
    audioStatus.textContent = `「${name}」上传成功`;
  } catch (error) {
    audioStatus.textContent = `上传失败 · ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

$("#reload-audio").addEventListener("click", loadAudioList);
$("#stop-audio").addEventListener("click", async () => {
  try {
    await audioRequest("/api/audio/pause", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    audioStatus.textContent = "已停止播放";
  } catch (error) {
    audioStatus.textContent = `停止失败 · ${error.message}`;
  }
});

volume.addEventListener("input", () => { $("#speaker-volume-value").textContent = volume.value; });
$("#volume-settings").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = $("#volume-status");
  status.textContent = "正在应用…";
  try {
    const data = await audioRequest("/api/audio/volume", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ volume: volume.valueAsNumber }),
    });
    status.textContent = `已设置为 ${data.volume}`;
  } catch (error) {
    status.textContent = `设置失败 · ${error.message}`;
  }
});

async function loadVolume() {
  try {
    const data = await audioRequest("/api/audio/volume");
    volume.value = data.volume;
    $("#speaker-volume-value").textContent = data.volume;
    $("#volume-status").textContent = "已同步";
  } catch (error) {
    $("#volume-status").textContent = `读取失败 · ${error.message}`;
  }
}

let handstandActive = false;
let handstandExiting = false;
function updateHandstandButton(active, exiting = false) {
  handstandActive = active;
  handstandExiting = exiting;
  const button = $("#handstand-toggle");
  button.textContent = exiting ? "退出等待中…" : active ? "退出倒立" : "倒立";
  button.disabled = exiting;
  button.setAttribute("aria-pressed", String(active));
}

$("#handstand-toggle").addEventListener("click", async () => {
  const button = $("#handstand-toggle");
  button.disabled = true;
  const exiting = handstandActive;
  try {
    hardStop(false);
    if (exiting) {
      if (await post("/api/handstand/exit")) updateHandstandButton(false, true);
    }
    else if (await post("/api/handstand")) updateHandstandButton(true);
  } finally {
    button.disabled = handstandExiting;
  }
});

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (handstandExiting) return;
    hardStop(false);
    await post(button.dataset.action);
  });
});

const patrolActions = {
  forward: "前进",
  backward: "后退",
  forward_distance: "前进指定距离",
  backward_distance: "后退指定距离",
  left: "左移",
  right: "右移",
  turn_left: "左转",
  turn_right: "右转",
  turn_left_90: "左转 90°",
  turn_right_90: "右转 90°",
  turn_left_180: "左转 180°",
  turn_right_180: "右转 180°",
  wait: "原地等待",
};
const fixedPatrolActions = new Set([
  "turn_left_90", "turn_right_90", "turn_left_180", "turn_right_180",
]);
const distancePatrolActions = new Set(["forward_distance", "backward_distance"]);

function defaultPatrolValue(action) {
  if (distancePatrolActions.has(action)) return 1;
  if (fixedPatrolActions.has(action)) return action.includes("180") ? 3.14 : 1.57;
  return 2;
}

function renumberPatrolSteps() {
  document.querySelectorAll(".path-step-number").forEach((number, index) => {
    number.textContent = String(index + 1).padStart(2, "0");
  });
}

function addPatrolStep(step = { action: "forward", duration: 2 }) {
  const row = document.createElement("div");
  row.className = "path-step";
  const options = Object.entries(patrolActions)
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  row.innerHTML = `
    <span class="path-step-number"></span>
    <select aria-label="巡逻动作">${options}</select>
    <label><input type="number" min="0.1" max="60" step="0.1" aria-label="持续时间"></label>
    <button type="button" class="move-step-up" aria-label="上移">↑</button>
    <button type="button" class="move-step-down" aria-label="下移">↓</button>
    <button type="button" class="remove-step">删除</button>`;
  row.querySelector("select").value = step.action;
  row.querySelector("input").value = step.distance ?? step.duration;
  const syncDuration = () => {
    const input = row.querySelector("input");
    const action = row.querySelector("select").value;
    const distance = distancePatrolActions.has(action);
    const fixed = fixedPatrolActions.has(action);
    input.disabled = false;
    input.parentElement.classList.toggle("fixed", fixed);
    input.parentElement.classList.toggle("distance", distance);
    input.min = distance ? "0.05" : "0.1";
    input.max = distance ? "20" : fixed ? "10" : "60";
    input.step = distance || fixed ? "0.05" : "0.1";
  };
  row.querySelector("select").addEventListener("change", () => {
    row.querySelector("input").value = defaultPatrolValue(row.querySelector("select").value);
    syncDuration();
  });
  syncDuration();
  row.querySelector(".move-step-up").addEventListener("click", () => {
    if (row.previousElementSibling) row.parentNode.insertBefore(row, row.previousElementSibling);
    renumberPatrolSteps();
  });
  row.querySelector(".move-step-down").addEventListener("click", () => {
    if (row.nextElementSibling) row.parentNode.insertBefore(row.nextElementSibling, row);
    renumberPatrolSteps();
  });
  row.querySelector(".remove-step").addEventListener("click", () => {
    row.remove();
    renumberPatrolSteps();
  });
  $("#patrol-steps").append(row);
  renumberPatrolSteps();
}

async function loadPatrolPath() {
  try {
    const response = await fetch("/api/patrol/path");
    if (!response.ok) throw new Error(response.statusText);
    const data = await response.json();
    $("#patrol-steps").replaceChildren();
    data.steps.forEach(addPatrolStep);
  } catch {
    addPatrolStep();
  }
}

async function savePatrolPath() {
  const steps = [...document.querySelectorAll(".path-step")].map((row) => {
    const action = row.querySelector("select").value;
    const value = Number(row.querySelector("input").value);
    return distancePatrolActions.has(action)
      ? { action, distance: value }
      : { action, duration: value };
  });
  try {
    const response = await fetch("/api/patrol/path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ steps }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || response.statusText);
    if (data.accepted === false) throw new Error("控制请求已过期或机器人正由其他操作控制");
    if (data.code != null && data.code !== 0) throw new Error(`SDK code ${data.code}`);
    $("#patrol-steps").replaceChildren();
    data.steps.forEach(addPatrolStep);
    commandStatus.textContent = "巡逻路径已保存";
    return true;
  } catch (error) {
    commandStatus.textContent = `保存失败 · ${error.message}`;
    return false;
  }
}

document.querySelectorAll("[data-add-patrol]").forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.addPatrol;
    const value = defaultPatrolValue(action);
    addPatrolStep(distancePatrolActions.has(action)
      ? { action, distance: value }
      : { action, duration: value });
  });
});
$("#save-patrol-path").addEventListener("click", savePatrolPath);
async function startPatrol(savePath = false) {
  if (handstandExiting) return;
  hardStop(false);
  if (savePath && !await savePatrolPath()) return;
  patrolRunning = Boolean(await post("/api/patrol/start", {
    vx: profiles.normal.vx,
    vyaw: profiles.normal.vyaw,
  }));
  updatePatrolButton();
  if (!patrolRunning) return;
  try {
    await audioRequest("/api/audio/play", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unique_id: "bf87bbfc-c62b-4e22-9393-f81b408552ab" }),
    });
    audioStatus.textContent = "巡检音频播放请求已提交";
  } catch (error) {
    audioStatus.textContent = `巡检音频播放失败 · ${error.message}`;
    commandStatus.textContent = audioStatus.textContent;
  }
}

$("#start-patrol").addEventListener("click", () => startPatrol(true));
$("#remote-patrol-toggle").addEventListener("click", async () => {
  if (patrolRunning) await hardStop();
  else await startPatrol();
});

$("#stop").addEventListener("click", hardStop);

const controlKeys = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE"]);
window.addEventListener("keydown", (event) => {
  if (event.code === "Space") {
    event.preventDefault();
    if (!event.repeat) hardStop();
    return;
  }
  if (!controlPage) return;
  if (event.target.closest("input, select, textarea, [contenteditable]")) return;
  if (!controlKeys.has(event.code)) return;
  event.preventDefault();
  pressedKeys.add(event.code);
  refreshMoveLoop();
});
window.addEventListener("keyup", (event) => {
  if (!controlKeys.has(event.code) || !pressedKeys.has(event.code)) return;
  event.preventDefault();
  pressedKeys.delete(event.code);
  refreshMoveLoop();
});

window.addEventListener("blur", () => {
  if (inputActive()) hardStop();
});
window.addEventListener("pagehide", () => {
  if (!inputActive()) return;
  const body = new Blob([JSON.stringify(controlToken())], { type: "application/json" });
  navigator.sendBeacon("/api/stop", body);
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden && inputActive()) hardStop();
});

camera.addEventListener("load", () => {
  cameraStatus.textContent = `● ${activeCameraName}`;
  cameraStatus.classList.remove("offline");
});
camera.addEventListener("error", () => {
  cameraStatus.textContent = "● 画面未连接";
  cameraStatus.classList.add("offline");
  window.setTimeout(() => { camera.src = `/api/video?t=${Date.now()}`; }, 1000);
});

function value(number, digits = 2) {
  return Number.isFinite(number) ? number.toFixed(digits) : "--";
}

function updateTelemetry(state) {
  if (typeof state.control?.handstand_active === "boolean") {
    updateHandstandButton(state.control.handstand_active, state.control.handstand_exiting);
  }
  connectionDot.classList.toggle("online", state.connected);
  connectionText.textContent = state.connected ? "已连接" : "未连接";
  $("#mode-header").textContent = `模式 ${state.mode}`;
  $("#battery").textContent = state.battery === null ? "--" : `${state.battery} %`;
  $("#mode").textContent = `Mode ${state.mode}`;
  $("#gait").textContent = `Gait ${state.gait_type}`;
  $("#position").textContent = `${value(state.position.x)} / ${value(state.position.y)} / ${value(state.position.z)} m`;
  $("#velocity").textContent = `${value(state.velocity.vx)} / ${value(state.velocity.vy)} / ${value(state.velocity.vz)} m/s`;
  $("#yaw-speed").textContent = `${value(state.yaw_speed)} rad/s`;
  $("#body-height").textContent = `${value(state.body_height)} m`;
  $("#imu").textContent = `${value(state.imu.roll)} / ${value(state.imu.pitch)} / ${value(state.imu.yaw)} rad`;
  const radarValues = state.range_obstacle.filter((distance) => Number.isFinite(distance) && distance > 0);
  $("#radar-range").textContent = radarValues.length
    ? state.range_obstacle.map((distance) => value(distance)).join(" / ") + " m（仅显示）"
    : "未提供有效距离（不影响巡逻）";
  $("#foot-force").textContent = state.foot_force.join(" / ");
  const maxTemperature = state.motor_temperature.length ? Math.max(...state.motor_temperature) : null;
  $("#motor-temp").textContent = maxTemperature === null ? "--" : `${maxTemperature} °C`;
  const patrolLabels = { idle: "未运行", running: "运行中", blocked: "已停止", error: "异常" };
  patrolRunning = state.patrol.status === "running";
  updatePatrolButton();
  $("#patrol-status").textContent = `巡逻：${patrolLabels[state.patrol.status] || state.patrol.status}${state.patrol.reason ? ` · ${state.patrol.reason}` : ""}`;
}

function connectState() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/state`);
  socket.addEventListener("message", (event) => updateTelemetry(JSON.parse(event.data)));
  socket.addEventListener("close", () => {
    connectionDot.classList.remove("online");
    connectionText.textContent = "重连中";
    window.setTimeout(connectState, 1000);
  });
  socket.addEventListener("error", () => socket.close());
}

connectState();
if (patrolPage) loadPatrolPath();
if (settingsPage) {
  loadAudioList();
  loadVolume();
  commandStatus.textContent = "设置就绪";
}
