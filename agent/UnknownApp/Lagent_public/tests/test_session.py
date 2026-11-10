"""核心模块单测：会话持久化 + 项目级指令文件（AGENTS.md）加载。

运行：
    cd agent/UnknownApp/Lagent_public
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.session import (  # noqa: E402
    AGENTS_MD_MAX_ENV,
    AGENTS_MD_ENV,
    SessionStore,
    agents_md_max_chars,
    agents_md_name,
    load_agents_md_content,
)


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = Path(self.tmp.name) / ".agents" / "sessions"
        self.store = SessionStore(self.sessions)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_roundtrip_save_load_list_delete(self) -> None:
        sid = self.store.create("回归测试")
        messages = [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么可以帮你"},
        ]
        self.store.save(sid, messages, title="改名后的会话")

        loaded = self.store.load(sid)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded), 3)
        self.assertEqual(loaded[1]["content"], "你好")

        listed = self.store.list_sessions()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], sid)
        self.assertEqual(listed[0]["title"], "改名后的会话")
        self.assertEqual(listed[0]["message_count"], 3)

        self.store.delete(sid)
        self.assertIsNone(self.store.load(sid))
        self.assertEqual(self.store.list_sessions(), [])

    def test_load_unknown_session_returns_none(self) -> None:
        self.assertIsNone(self.store.load("19990101-000000"))

    def test_save_without_prior_create_still_works(self) -> None:
        sid = "manual-session"
        self.store.save(sid, [{"role": "user", "content": "hi"}])
        loaded = self.store.load(sid)
        self.assertEqual(loaded, [{"role": "user", "content": "hi"}])


class AgentsMdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._env_backup = {k: os.environ.get(k) for k in (AGENTS_MD_ENV, AGENTS_MD_MAX_ENV)}

    def tearDown(self) -> None:
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_default_name_is_agents_md(self) -> None:
        os.environ.pop(AGENTS_MD_ENV, None)
        self.assertEqual(agents_md_name(), "AGENTS.md")

    def test_filename_configurable_via_env(self) -> None:
        os.environ[AGENTS_MD_ENV] = "AGENT.md"
        self.assertEqual(agents_md_name(), "AGENT.md")
        (self.root / "AGENT.md").write_text("规则：用中文回答", encoding="utf-8")
        content, path = load_agents_md_content(self.root)
        self.assertEqual(content, "规则：用中文回答")
        self.assertTrue(path)

    def test_missing_file_returns_empty(self) -> None:
        os.environ[AGENTS_MD_ENV] = "AGENTS_NOT_EXIST.md"
        content, path = load_agents_md_content(self.root)
        self.assertEqual(content, "")
        self.assertIsNone(path)

    def test_long_file_is_truncated_with_notice(self) -> None:
        os.environ[AGENTS_MD_ENV] = "AGENTS_TRUNC_TEST.md"
        os.environ[AGENTS_MD_MAX_ENV] = "10"
        body = "A" * 50
        (self.root / "AGENTS_TRUNC_TEST.md").write_text(body, encoding="utf-8")
        content, _ = load_agents_md_content(self.root)
        self.assertTrue(content.startswith("A" * 10))
        self.assertIn("已截断", content)
        self.assertLess(len(content), len(body) + 60, "截断后不应完整保留原文")

    def test_max_chars_env_falls_back_on_invalid_value(self) -> None:
        os.environ[AGENTS_MD_MAX_ENV] = "abc"
        self.assertEqual(agents_md_max_chars(), 4000)
        os.environ[AGENTS_MD_MAX_ENV] = "-5"
        self.assertEqual(agents_md_max_chars(), 4000)
        os.environ[AGENTS_MD_MAX_ENV] = "1200"
        self.assertEqual(agents_md_max_chars(), 1200)


if __name__ == "__main__":
    unittest.main()
