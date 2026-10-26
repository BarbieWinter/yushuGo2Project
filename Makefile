SHELL := /bin/bash
.DEFAULT_GOAL := help

APP_DIR := app
VENV := .venv
PY := $(VENV)/bin/python
SDK_DIR := ../unitree_sdk2_python
HOST ?= 127.0.0.1
PORT ?= 8000

# 自动找持有 192.168.123.x 的网卡；找不到时用 IFACE 覆盖，例如 IFACE=en8 make dev
IFACE ?= $(shell ifconfig 2>/dev/null | awk '/^[a-zA-Z0-9_.-]+:/{iface=$$1} /inet 192\.168\.123\./{sub(":","",iface); print iface; exit}')

.PHONY: help install dev stop test clean

help:
	@echo "make install            安装 Python 依赖和 Unitree SDK"
	@echo "make dev [IFACE=en8]    启动 go2_web"
	@echo "make stop               停止 uvicorn"
	@echo "make test               运行测试"
	@echo "make clean              清理缓存"
	@echo ""
	@echo "默认地址: http://$(HOST):$(PORT)/"
	@echo "检测到的网卡: $(IFACE)"

install:
	@command -v uv >/dev/null 2>&1 || { echo "缺少 uv，请先安装 uv"; exit 1; }
	@test -x $(PY) || uv venv $(VENV)
	uv pip install --python $(PY) -e $(SDK_DIR) -r $(APP_DIR)/requirements.txt -r $(APP_DIR)/requirements-test.txt
	@echo "依赖安装完成"

dev:
	@test -x $(PY) || { echo "缺少 $(PY)，请先执行 make install"; exit 1; }
	@test -n "$(IFACE)" || { echo "找不到 192.168.123.x 网卡，请用 IFACE=en8 make dev"; exit 1; }
	@if lsof -nP -iTCP:$(PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "端口 $(PORT) 已被占用，先执行 make stop"; \
		lsof -nP -iTCP:$(PORT) -sTCP:LISTEN; \
		exit 1; \
	fi
	@echo "网卡: $(IFACE)"
	@echo "地址: http://$(HOST):$(PORT)/"
	cd $(APP_DIR) && GO2_IFACE=$(IFACE) ../$(PY) -m uvicorn app:app --host $(HOST) --port $(PORT)

stop:
	-pkill -f 'uvicorn app:app'

test:
	cd $(APP_DIR) && ../$(PY) -m pytest -q

clean:
	find $(APP_DIR) -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(APP_DIR)/.pytest_cache
