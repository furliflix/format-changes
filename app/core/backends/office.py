# -*- coding: utf-8 -*-
"""LibreOffice 无头模式后端：Word / Excel / PPT / 文本文档 之间的转换。"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..cancel import CancelToken
from ..deps import Deps, popen_flags
from ..errors import CancelledError, ConvertError

# 指定导出过滤器能避免中文编码 / 格式上的意外；
# 值为 None 表示直接写扩展名（让 LibreOffice 自己挑最合适的导出器）。
LO_FILTERS: dict[str, str | None] = {
    "pdf": None,
    "txt": "txt:Text (encoded):UTF8",
    "html": "html:HTML (StarWriter)",
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76",
    "docx": None,
    "xlsx": None,
    "pptx": None,
    "odt": "odt:writer8",
    "ods": "ods:calc8",
    "odp": "odp:impress8",
    "rtf": "rtf:Rich Text Format",
    "xls": None,
    "ppt": None,
}

LO_TIMEOUT = 600  # 秒


class OfficeBackend:
    def __init__(self, deps: Deps):
        self.deps = deps

    def convert(
        self,
        src: Path,
        target: str,
        tmp_out: Path,
        q,
        progress,
        cancel: CancelToken,
    ) -> None:
        self.deps.need_soffice()
        assert self.deps.soffice
        soffice = self.deps.soffice

        with tempfile.TemporaryDirectory(prefix=".fw-lo-") as td:
            tdp = Path(td)
            outdir = tdp / "out"
            outdir.mkdir()
            profile = tdp / "profile"
            profile.mkdir()
            logfile = tdp / "lo.log"

            filt = LO_FILTERS.get(target)
            attempts = ([filt] if filt else []) + [target]  # 第二遍用扩展名兜底
            produced: Path | None = None
            last_err = ""

            for i, f in enumerate(attempts):
                if cancel.cancelled():
                    raise CancelledError()
                progress(None, "正在转换（LibreOffice）…")
                cmd = [
                    soffice,
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless", "--norestore", "--invisible", "--nologo", "--nolockcheck",
                    "--convert-to", f,
                    "--outdir", str(outdir),
                    str(src),
                ]
                rc, out = self._run(cmd, cancel, progress, logfile)
                # 正常情况下输出文件叫 <源文件名去扩展名>.<目标扩展名>
                cand = outdir / (src.stem + "." + target)
                if cand.exists() and cand.stat().st_size > 0:
                    produced = cand
                    break
                for p in outdir.glob(src.stem + ".*"):
                    if p.suffix.lower().lstrip(".") == target.lower() and p.stat().st_size > 0:
                        produced = p
                        break
                if produced:
                    break
                last_err = out
                # 清空输出目录再重试一次
                for p in outdir.iterdir():
                    try:
                        p.unlink()
                    except OSError:
                        pass

            if not produced:
                raise ConvertError(
                    "LibreOffice 转换失败：\n" + (last_err.strip()[-500:] or "没有生成输出文件")
                )
            try:
                shutil.move(str(produced), str(tmp_out))
            except Exception as e:
                raise ConvertError(f"无法保存输出文件：{e}") from e
            progress(1.0, "完成")

    # ------------------------------------------------------------ 进程管理

    def _run(
        self,
        cmd: list[str],
        cancel: CancelToken,
        progress,
        logfile: Path,
    ) -> tuple[int, str]:
        """跑 soffice 并轮询等待；期间报"已用 x 秒"，可随时取消。

        输出重定向到文件，避免管道缓冲区写满导致死锁。
        """
        with open(str(logfile), "wb") as log:
            proc = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                **popen_flags(),
            )
            cancel.attach(proc)
            start = time.time()
            try:
                while proc.poll() is None:
                    if cancel.cancelled():
                        proc.kill()
                        proc.wait()
                        raise CancelledError()
                    elapsed = time.time() - start
                    if elapsed > LO_TIMEOUT:
                        proc.kill()
                        proc.wait()
                        return 1, "LibreOffice 超时（超过 10 分钟）"
                    progress(None, f"正在转换（LibreOffice）… 已用 {int(elapsed)} 秒")
                    time.sleep(0.4)
                rc = proc.returncode
            finally:
                cancel.detach(proc)
        try:
            out = logfile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            out = ""
        return rc, out
