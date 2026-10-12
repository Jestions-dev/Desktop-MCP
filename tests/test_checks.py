# -*- coding: utf-8 -*-
"""
跑 tools/ 下的检查脚本，把结果当测试。

为什么这么包装：那些脚本是**给人和 agent 看的报告**（打印表格、结论行），
直接改写成 unittest 会把可读性搞没。包装成子进程调用，两边都保住：
  · `python -m unittest` 能跑（CI 友好）
  · `python tools/check_xxx.py` 仍能单独跑（人看得懂）

所有被包装的脚本在检查失败时返回非 0（这是硬要求，否则测试永远绿）。
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

# (脚本名, 说明, 超时秒)
SCRIPTS = [
    ("check_protocol.py",       "MCP 协议合规（34 项）",            180),
    ("check_trajectory.py",     "轨迹数学：缩放/旋转/回放（27 项）", 120),
    ("check_purity.py",         "轨迹纯净度：无夹带点击",            60),
    ("check_coverage.py",       "四象限轨迹覆盖",                   60),
    ("check_speed_preserve.py", "时间按距离缩放（112 组）",          180),
    ("check_fitts.py",          "距离与时长的相关性",                60),
    ("check_pull_vs_push.py",   "推/拉两种发力的差异",               60),
    ("check_curves.py",         "轨迹转折与采样密度",                60),
    ("check_humanness.py",      "速度剖面的人味",                    60),
    ("final_check.py",          "端到端：观察框完整往返（13 项）",   180),
]


def _make(name, desc, timeout):
    def test(self):
        script = TOOLS / name
        if not script.is_file():
            self.skipTest(f"{name} 不在")
        r = subprocess.run([sys.executable, str(script)], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        tail = "\n".join((r.stdout or "").strip().splitlines()[-12:])
        self.assertEqual(r.returncode, 0,
                         f"{desc}\n--- 输出末尾 ---\n{tail}\n--- stderr ---\n"
                         f"{(r.stderr or '')[-800:]}")
    test.__name__ = "test_" + name.replace(".py", "").replace("-", "_")
    test.__doc__ = desc
    return test


class Checks(unittest.TestCase):
    """跑 tools/ 下的检查脚本。"""


for _n, _d, _t in SCRIPTS:
    setattr(Checks, "test_" + _n.replace(".py", "").replace("-", "_"),
            _make(_n, _d, _t))


if __name__ == "__main__":
    unittest.main(verbosity=2)
