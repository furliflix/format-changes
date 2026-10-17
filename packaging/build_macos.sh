#!/usr/bin/env bash
# 在 macOS 上一键打包出「Format Changes.app」并生成可分发的 dmg / zip（含给老师的说明）。
#
# 用法（在项目根目录）：
#     bash packaging/build_macos.sh
#
# 打包结果：
#     dist/FormatChanges.app
#     dist/FormatChanges-<架构>.dmg          ← 推荐发给老师（拖进「应用程序」即安装）
#     dist/FormatChanges-macOS-<架构>.zip    ← 备用（内含 App 和说明）
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> [1/7] 准备 Python 虚拟环境"
python3 -m venv .venv-build
# shellcheck disable=SC1091
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

echo "==> [2/7] 生成图标"
python packaging/make_icon.py
if command -v iconutil >/dev/null 2>&1; then
  iconutil -c icns packaging/AppIcon.iconset -o assets/AppIcon.icns
  echo "    已生成 assets/AppIcon.icns"
else
  echo "    警告：没有 iconutil（不是 macOS？），将使用默认图标"
fi

echo "==> [3/7] 运行自检（各种格式实际转一遍）"
if ! python tests/smoke_cli.py; then
  echo "    注意：自检有失败项，请先看看上面的输出再决定是否继续。"
fi

echo "==> [4/7] PyInstaller 打包 .app"
rm -rf build dist
python -m PyInstaller --noconfirm --clean FormatChanges.spec

echo "==> [5/7] 生成压缩包（ditto 保留权限与符号链接）"
ARCH="$(uname -m)"
STAGE="dist/发送给老师"
mkdir -p "$STAGE"
ditto "dist/FormatChanges.app" "$STAGE/Format Changes.app"
cp "packaging/给老师的说明.txt" "$STAGE/"
ZIP="dist/FormatChanges-macOS-${ARCH}.zip"
ditto -c -k --sequesterRsrc --keepParent "$STAGE" "$ZIP"

echo "==> [6/7] 制作 DMG 安装包（打开后拖进「应用程序」即安装）"
DMG="dist/FormatChanges-${ARCH}.dmg"
rm -rf dmg_stage
mkdir -p dmg_stage
ditto "dist/FormatChanges.app" "dmg_stage/Format Changes.app"
cp "packaging/给老师的说明.txt" dmg_stage/
ln -s /Applications dmg_stage/Applications
hdiutil create -volname "Format Changes" -srcfolder dmg_stage -ov -format UDZO "$DMG"

echo "==> [7/7] 完成！"
echo "    App    ：dist/FormatChanges.app"
echo "    DMG    ：$DMG（打开后把 App 拖进「应用程序」）"
echo "    压缩包 ：$ZIP（备用，内含 App 和使用说明）"
echo "    老师第一次打开需要：右键 App -> 打开 -> 再点一次「打开」。"
echo
echo "可选（有 Apple 开发者账号时，做正式签名和公证，避免被 Gatekeeper 拦截）："
echo "  codesign --deep --force --options runtime --sign \"Developer ID Application: 你的名字 (TEAMID)\" dist/FormatChanges.app"
echo "  xcrun notarytool submit \"$DMG\" --apple-id 你的AppleID --team-id TEAMID --password 应用专用密码 --wait"
echo "  xcrun stapler staple dist/FormatChanges.app"
