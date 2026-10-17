#!/usr/bin/env bash
# 备选方案：如果老师电脑上装了 Python 3，双击这个脚本就能直接运行（不用打包）。
# 第一次运行会自动创建虚拟环境并安装依赖（需要联网，约 2-5 分钟）。
#
# 注意：从网上下载后第一次双击可能被 macOS 拦下，右键 -> 打开 即可。
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "没有找到 Python 3" message "请先安装 Python 3（https://www.python.org/downloads/），或者改用打包好的 App。"'
  exit 1
fi

if [ ! -d .venv-mac ]; then
  echo "首次运行：正在准备环境（需要联网）…"
  python3 -m venv .venv-mac
  ./.venv-mac/bin/python -m pip install --upgrade pip
  ./.venv-mac/bin/python -m pip install -r requirements.txt
fi

exec ./.venv-mac/bin/python main.py
