#!/usr/bin/env bash
# 在 macOS 上一键打包出「Format Changes.app」并生成可分发的 zip（含给老师的说明）。
#
# 用法（在项目根目录）：
#     bash packaging/build_macos.sh
#
# 打包结果：
#     dist/FormatChanges.app
#     dist/FormatChanges-macOS-<架构>.zip   ← 把这个 zip 发给老师
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> [1/6] 准备 Python 虚拟环境"
python3 -m venv .venv-build
# shellcheck disable=SC1091
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

echo "==> [2/6] 生成图标"
python packaging/make_icon.py
if command -v iconutil >/dev/null 2>&1; then
  iconutil -c icns packaging/AppIcon.iconset -o assets/AppIcon.icns
  echo "    已生成 assets/AppIcon.icns"
else
  echo "    警告：没有 iconutil（不是 macOS？），将使用默认图标"
fi

echo "==> [3/6] 运行自检（各种格式实际转一遍）"
if ! python tests/smoke_cli.py; then
  echo "    注意：自检有失败项，请先看看上面的输出再决定是否继续。"
fi

echo "==> [4/6] PyInstaller 打包 .app"
rm -rf build dist
python -m PyInstaller --noconfirm --clean FormatChanges.spec

echo "==> [5/6] 生成压缩包（ditto 保留权限与符号链接）"
ARCH="$(uname -m)"
STAGE="dist/发送给老师"
mkdir -p "$STAGE"
cp -R "dist/FormatChanges.app" "$STAGE/"
cp "packaging/给老师的说明.txt" "$STAGE/"
ZIP="dist/FormatChanges-macOS-${ARCH}.zip"
ditto -c -k --sequesterRsrc --keepParent "$STAGE" "$ZIP"

echo "==> [6/6] 完成！"
echo "    App    ：dist/FormatChanges.app"
echo "    压缩包 ：$ZIP（内含 App 和使用说明，直接发给老师）"
echo "    老师第一次打开需要：右键 App -> 打开 -> 再点一次「打开」。"
echo
echo "可选（有 Apple 开发者账号时，做正式签名和公证，避免被 Gatekeeper 拦截）："
echo "  codesign --deep --force --options runtime --sign \"Developer ID Application: 你的名字 (TEAMID)\" dist/FormatChanges.app"
echo "  xcrun notarytool submit \"$ZIP\" --apple-id 你的AppleID --team-id TEAMID --password 应用专用密码 --wait"
echo "  xcrun stapler staple dist/FormatChanges.app"
