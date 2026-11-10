"""宠物医院 MCP · 后端访问层。

职责单一：把 REST 调用、重试、超时、错误码映射、调用日志集中在这里。
工具层不直接碰网络，测试时用 FakeClient 注入即可离线验证。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT = 8.0
DEFAULT_RETRIES = 2
RETRY_BACKOFF = 0.25


class BackendError(Exception):
    """带错误码的后端错误：code 供模型与客户端分支处理，message 供人读。"""

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class CallLog:
    """结构化调用日志：一条 JSON 一行，写到 stderr（不污染 stdio 的协议通道）。"""

    stream: Any = sys.stderr
    enabled: bool = True
    records: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, **fields: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            **fields,
        }
        self.records.append(record)
        if self.enabled and self.stream is not None:
            self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.stream.flush()


class PetHospitalClient:
    """REST 后端客户端：统一信封解析 + 超时 + 重试 + 错误码。"""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        http: Any | None = None,
        log: CallLog | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.log = log or CallLog()
        self._sleep = sleep
        self._http = http or self._build_http()

    # ------------------------------------------------------------------
    def _build_http(self) -> Any:
        import httpx2

        return httpx2.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        tool: str = "",
    ) -> Any:
        """发请求并把统一信封解开，返回 data 字段。失败抛 BackendError。"""
        started = time.perf_counter()
        attempts = 0
        last_error: BackendError | None = None

        while attempts <= self.retries:
            attempts += 1
            try:
                response = self._http.request(
                    method,
                    self.base_url + path,
                    params=_clean(params),
                    json=body,
                )
            except Exception as exc:  # 网络层异常：连接失败 / 超时
                code = "UPSTREAM_TIMEOUT" if _looks_timeout(exc) else "UPSTREAM_UNAVAILABLE"
                last_error = BackendError(code, f"无法连接宠物医院服务（{self.base_url}）：{exc}")
                if attempts <= self.retries:
                    self._sleep(RETRY_BACKOFF * attempts)
                    continue
                self._finish(started, tool, method, path, attempts, False, last_error.code)
                raise last_error

            status = int(getattr(response, "status_code", 200))
            if status >= 500 and attempts <= self.retries:
                self._sleep(RETRY_BACKOFF * attempts)
                continue

            try:
                payload = response.json()
            except Exception:
                last_error = BackendError(
                    "BAD_UPSTREAM",
                    f"上游返回的不是 JSON（HTTP {status}）：{_snippet(response)}",
                    status,
                )
                self._finish(started, tool, method, path, attempts, False, last_error.code)
                raise last_error

            code, message = self._validate_envelope(payload, status)
            if code != 0:
                error = BackendError(
                    _code_for_status(status),
                    message or f"上游拒绝请求（HTTP {status}，业务码 {code}）",
                    status,
                )
                self._finish(started, tool, method, path, attempts, False, error.code)
                raise error

            self._finish(started, tool, method, path, attempts, True, "OK")
            return payload.get("data")

        # 理论上不可达
        error = last_error or BackendError("UPSTREAM_UNAVAILABLE", "请求失败")
        self._finish(started, tool, method, path, attempts, False, error.code)
        raise error

    # ------------------------------------------------------------------
    def _validate_envelope(self, payload: Any, status: int) -> tuple[int, str]:
        """校验统一信封 {code,message,data}：不做原样透传。"""
        if not isinstance(payload, dict):
            raise BackendError("BAD_UPSTREAM", f"上游响应不是对象（HTTP {status}）", status)
        if "code" not in payload:
            raise BackendError("BAD_UPSTREAM", f"上游响应缺少 code 字段（HTTP {status}）", status)
        try:
            code = int(payload.get("code") or 0)
        except (TypeError, ValueError):
            raise BackendError("BAD_UPSTREAM", "上游 code 字段不是整数", status)
        message = str(payload.get("message") or "")
        if status >= 400 and code == 0:
            code = status
        return code, message

    def _finish(
        self,
        started: float,
        tool: str,
        method: str,
        path: str,
        attempts: int,
        ok: bool,
        code: str,
    ) -> None:
        self.log.emit(
            event="tool_call",
            tool=tool or path,
            method=method,
            path=path,
            attempts=attempts,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            ok=ok,
            code=code,
        )


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}


def _looks_timeout(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    return "timeout" in name or "timedout" in name


def _code_for_status(status: int) -> str:
    if status == 404:
        return "UPSTREAM_NOT_FOUND"
    if status == 408:
        return "UPSTREAM_TIMEOUT"
    if 400 <= status < 500:
        return "UPSTREAM_REJECTED"
    return "UPSTREAM_ERROR"


def _snippet(response: Any, limit: int = 160) -> str:
    text = str(getattr(response, "text", "") or "")
    return text.replace("\n", " ")[:limit]
