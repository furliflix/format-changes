# -*- coding: utf-8 -*-
"""命令行模式：python main.py --cli ...

例：
    python main.py --cli 录音.mp3 -t ogg
    python main.py --cli 视频.mkv -t mp4 -o 输出目录 -q high
    python main.py --cli 讲义.docx -t pdf
    python main.py --cli 某个文件夹 -t mp3
    python main.py --cli 文件.pdf --list
    python main.py --cli --check
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from . import APP_NAME, APP_VERSION
from .core.cancel import CancelToken
from .core.engine import Converter
from .core.errors import CancelledError, ConvertError
from .core.formats import PRESETS, SOURCE_GROUPS


def _collect_inputs(raw_list, files: list[Path], unsupported: list[str]) -> None:
    for raw in raw_list:
        p = Path(raw)
        if p.is_dir():
            for sub in sorted(p.rglob("*")):
                if sub.is_file():
                    if sub.suffix.lower().lstrip(".") in SOURCE_GROUPS:
                        files.append(sub)
                    else:
                        unsupported.append(str(sub))
        elif p.is_file():
            if p.suffix.lower().lstrip(".") in SOURCE_GROUPS:
                files.append(p)
            else:
                unsupported.append(str(p))
        else:
            print(f"找不到：{p}")
            unsupported.append(str(p))


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(prog=f"{APP_NAME} 命令行模式")
    ap.add_argument("inputs", nargs="*", help="源文件或文件夹")
    ap.add_argument("-t", "--to", help="目标格式，如 mp3 / mp4 / pdf")
    ap.add_argument("-o", "--out", help="输出目录（默认与源文件相同）")
    ap.add_argument("-q", "--quality", choices=[p.key for p in PRESETS],
                    default="balanced", help="画质预设")
    ap.add_argument("--overwrite", action="store_true", help="覆盖同名文件")
    ap.add_argument("--list", action="store_true", help="列出每个文件可转换的目标格式")
    ap.add_argument("--check", action="store_true", help="检查运行环境")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = ap.parse_args(argv)

    conv = Converter()

    if args.check:
        print(f"{APP_NAME} {APP_VERSION}")
        for name, ok, desc in conv.deps.summary_lines():
            print(f"[{'OK' if ok else '--'}] {name}：{desc}")
        for name, ok in conv.deps.key_encoders():
            print(f"[{'OK' if ok else '--'}] 编码器 {name}")
        return 0

    if not args.inputs:
        ap.print_help()
        return 2

    files: list[Path] = []
    unsupported: list[str] = []
    _collect_inputs(args.inputs, files, unsupported)
    if unsupported:
        print(f"（跳过 {len(unsupported)} 个不支持的文件）")

    if args.list:
        for f in files:
            targets = conv.targets_for(f)
            desc = ", ".join(
                t.ext if t.available else f"{t.ext}(不可用:{t.note})" for t in targets
            )
            print(f"{f}\n    → {desc}")
        return 0

    if not args.to:
        print("请用 -t 指定目标格式（例如 -t pdf）。")
        return 2
    if not files:
        print("没有可转换的文件。")
        return 1

    token = CancelToken()

    def _sigint(_signum, _frame):
        print("\n正在取消…")
        token.cancel()

    try:
        signal.signal(signal.SIGINT, _sigint)
    except Exception:
        pass

    ok = fail = 0
    for f in files:
        if token.cancelled():
            break
        last_text = {"s": ""}

        def cb(frac, text, _last=last_text, _f=f):
            if frac is None:
                _last["s"] = text or ""
            else:
                bar = f"\r[*] {_f.name} -> {args.to} … {int(frac * 100):3d}%"
                print(bar.ljust(70), end="", flush=True)

        try:
            out = conv.convert(
                f, args.to,
                dst_dir=Path(args.out) if args.out else None,
                quality=args.quality, overwrite=args.overwrite,
                progress=cb, cancel=token,
            )
            ok += 1
            print(f"\r[✓] {f.name} -> {out}".ljust(70))
        except CancelledError:
            break
        except ConvertError as e:
            fail += 1
            print(f"\r[✗] {f.name}".ljust(70))
            print(f"    {e}")

    if token.cancelled():
        print(f"已取消。完成 {ok} 个，失败 {fail} 个。")
        return 130
    print(f"完成：成功 {ok} 个，失败 {fail} 个。")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
