SHELL := sh
.DEFAULT_GOAL := help

APP_DIR := app
VENV := .venv
SDK_DIR := ../unitree_sdk2_python
HOST ?= 127.0.0.1
PORT ?= 8000

# 网卡默认自动检测（见 app/netiface.py）：Windows 返回“以太网”“Ethernet”这类
# 适配器别名，Linux / macOS 返回 eth0、en8 这类接口名，换电脑不用改名字。
# 需要用其他网卡时再覆盖，例如 IFACE=<网卡名> make dev。
IFACE ?=

# Windows 使用 .venv\Scripts\python.exe；macOS / Ubuntu 使用 .venv/bin/python。
# Windows 需要 Git Bash 或 MSYS2 提供 sh / make，原生 cmd 不支持这些 recipe。
ifeq ($(OS),Windows_NT)
	VENV_PY := $(VENV)/Scripts/python.exe
	STOP_CMD = pids=$$(netstat -ano | grep ':$(PORT) ' | awk '{print $$5}' | sort -u); [ -z "$$pids" ] || for pid in $$pids; do taskkill //F //PID $$pid >/dev/null 2>&1 || true; done
else
	VENV_PY := $(VENV)/bin/python
	STOP_CMD = pids=$$(lsof -ti tcp:$(PORT) 2>/dev/null); [ -z "$$pids" ] || kill $$pids
endif

.PHONY: help install dev start stop test clean

help:
	@echo "make install             安装 Python 依赖和 Unitree SDK"
	@echo "make dev                 启动 go2_web（自动检测机器人网卡）"
	@echo "make dev IFACE=<name>    指定网卡启动"
	@echo "make start               同 make dev"
	@echo "make stop                停止 8000 端口上的服务"
	@echo "make test                运行测试"
	@echo "make clean               清理缓存"
	@echo ""
	@echo "默认地址: http://$(HOST):$(PORT)/"
	@echo "网卡: $(if $(IFACE),$(IFACE),自动检测)"

install:
	@command -v uv >/dev/null 2>&1 || { echo "缺少 uv，请先安装 uv"; exit 1; }
	@test -x "$(VENV_PY)" || uv venv "$(VENV)"
	uv pip install --python "$(VENV_PY)" -e "$(SDK_DIR)" -r "$(APP_DIR)/requirements.txt" -r "$(APP_DIR)/requirements-test.txt"
	@echo "依赖安装完成"

dev:
	@test -x "$(VENV_PY)" || { echo "缺少 $(VENV_PY)，请先执行 make install"; exit 1; }
	@$(VENV_PY) -c "import socket,sys; s=socket.socket(); s.settimeout(0.2); sys.exit('端口 $(PORT) 已被占用，先执行 make stop') if s.connect_ex(('127.0.0.1',$(PORT)))==0 else None"
	@echo "网卡: $(if $(IFACE),$(IFACE),自动检测)"
	@echo "地址: http://$(HOST):$(PORT)/"
	cd $(APP_DIR) && GO2_IFACE="$(IFACE)" ../$(VENV_PY) -m uvicorn app:app --host "$(HOST)" --port "$(PORT)"

start: dev

stop:
	-@$(STOP_CMD)

test:
	cd $(APP_DIR) && ../$(VENV_PY) -m pytest -q

clean:
	find $(APP_DIR) -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(APP_DIR)/.pytest_cache
