# -*- coding: utf-8 -*-
"""工具注册表与命令行的基本检查（纯静态，不碰屏幕）。"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Tools(unittest.TestCase):
    def test_tool_registry(self):
        from desktop_mcp import tools as T
        names = [t["name"] for t in T.list_tools()]
        self.assertTrue(names, "工具列表为空")
        self.assertEqual(set(T._DISPATCH), set(names), "注册表与工具名不一致")
        self.assertEqual(len(names), len(set(names)), "工具名重复")
        for t in T.list_tools():
            self.assertTrue(t["name"].startswith("desktop_"), t["name"])
            self.assertTrue(t.get("description", "").strip(), t["name"])
            self.assertEqual(t["inputSchema"]["type"], "object", t["name"])

    def test_server_starts_and_speaks_mcp(self):
        """跑一次真实握手：initialize + tools/list"""
        import json
        p = subprocess.Popen([sys.executable, "-m", "desktop_mcp.server"],
                             cwd=str(ROOT), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", bufsize=1)
        try:
            p.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18",
                           "capabilities": {}}}) + "\n")
            p.stdin.flush()
            line = p.stdout.readline()
            msg = json.loads(line)
            self.assertEqual(msg["jsonrpc"], "2.0")
            self.assertEqual(msg["id"], 1)
            self.assertIn(msg["result"]["protocolVersion"],
                          ("2025-06-18", "2025-03-26", "2024-11-05"))
            self.assertIn("tools", msg["result"]["capabilities"])

            p.stdin.write(json.dumps({
                "jsonrpc": "2.0", "id": 2, "method": "tools/list",
                "params": {}}) + "\n")
            p.stdin.flush()
            for _ in range(6):                    # 跳过通知
                m = json.loads(p.stdout.readline())
                if m.get("id") == 2:
                    break
            self.assertTrue(m["result"]["tools"])
        finally:
            p.stdin.close()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()

    def test_cli_help(self):
        r = subprocess.run([sys.executable, "-m", "desktop_mcp.server", "--help"],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("desktop-mcp", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
