"""宠物医院 MCP Server。

把 pet-hospital-mcp 的 REST 能力按 MCP 协议暴露给模型使用：
- 传输：stdio（本地进程管道，默认）/ streamable-http（HTTP 端点）
- 工具：10 个业务工具，参数带类型、枚举、范围约束与中文说明
- 错误：统一结构化返回 {ok, code, message, hint}
- 韧性：后端超时 8s、失败重试 2 次、每次调用写一行结构化日志到 stderr

用法：
    python -m mcp_server                       # stdio，供 Claude Desktop / Lagent 等接入
    python -m mcp_server --transport http --port 8765
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from typing import Annotated, Any, Literal

from pydantic import Field

from mcp.server import MCPServer

from .backend import DEFAULT_BASE_URL, DEFAULT_RETRIES, DEFAULT_TIMEOUT, BackendError, CallLog, PetHospitalClient

SERVER_NAME = "pet-hospital-mcp"
SERVER_VERSION = "1.0.0"

SPECIES = ["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
STATUSES = ["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
CHARGE_CATEGORIES = ["检查", "药品", "手术", "住院", "疫苗", "其他"]
SORTS = ["createdAt", "totalCost", "name"]
ORDERS = ["asc", "desc"]

HINTS = {
    "VALIDATION_ERROR": "检查参数类型、必填项与取值枚举后重试。",
    "UPSTREAM_TIMEOUT": "宠物医院服务响应超时，确认服务在运行，或缩小 pageSize 后重试。",
    "UPSTREAM_UNAVAILABLE": "宠物医院服务未启动或地址不对，先用 GET /health 探活。",
    "UPSTREAM_NOT_FOUND": "档案 ID 不存在，可先用 list_pets / search_pets 查出正确 ID。",
    "UPSTREAM_REJECTED": "业务字段被后端拒绝，参考 message 里列出的合法取值。",
    "UPSTREAM_ERROR": "后端 5xx，稍后重试或查看服务端日志。",
    "BAD_UPSTREAM": "后端返回格式异常，确认访问的是宠物医院 REST 服务而不是别的服务。",
}


def ok(data: Any = None, code: str = "OK", message: str = "") -> str:
    return json.dumps({"ok": True, "code": code, "message": message or "成功", "data": data}, ensure_ascii=False)


def fail(code: str, message: str, hint: str | None = None) -> str:
    return json.dumps(
        {"ok": False, "code": code, "message": message, "hint": hint or HINTS.get(code, "")},
        ensure_ascii=False,
    )


def build_server(
    base_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    http: Any | None = None,
    log_stream: Any | None = sys.stderr,
    log: CallLog | None = None,
) -> MCPServer:
    """装配 MCP server。测试可注入 http 假客户端、日志器与空日志流。"""
    log = log or CallLog(stream=log_stream)
    client = PetHospitalClient(
        base_url=base_url or os.environ.get("PET_HOSPITAL_BASE_URL", DEFAULT_BASE_URL),
        timeout=timeout,
        retries=retries,
        http=http,
        log=log,
    )
    mcp = MCPServer(
        SERVER_NAME,
        SERVER_VERSION,
        instructions=(
            "宠物医院运营助手。可查询宠物档案、按主人/医生/疾病/状态检索、追加病历与收费、"
            "拉取单只宠物汇总与医院经营统计。宠物 ID 形如 PET-000001，未知时先用 list_pets 或 search_pets 查。"
        ),
        log_level="WARNING",
    )

    def guard(tool_name: str, fn):
        """把工具异常统一转成结构化返回，不让 traceback 直接落到协议通道。"""
        try:
            return fn()
        except BackendError as exc:
            return fail(exc.code, exc.message)
        except Exception as exc:  # 兜底：未预期异常也要可读
            log.emit(event="tool_error", tool=tool_name, ok=False, code="INTERNAL_ERROR", detail=str(exc)[:200])
            return fail("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", "这是工具内部异常，请把 message 反馈给开发者。")

    # ---------------- 工具 1：列表 ----------------
    @mcp.tool(description="查询宠物列表，支持分页、种类/状态过滤与排序。返回 {ok, code, data:{items, total, page, pageSize}}。")
    async def list_pets(
        page: Annotated[int, Field(ge=1, description="页码，从 1 开始")] = 1,
        page_size: Annotated[int, Field(ge=1, le=100, description="每页条数，1-100")] = 10,
        species: Annotated[Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"] | None, Field(description="按宠物种类过滤，可选")] = None,
        status: Annotated[Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"] | None, Field(description="按就诊状态过滤，可选")] = None,
        sort_by: Annotated[Literal["createdAt", "totalCost", "name"] | None, Field(description="排序字段：建档时间/总花费/名称")] = None,
        order: Annotated[Literal["asc", "desc"] | None, Field(description="排序方向，默认 desc")] = None,
    ) -> str:
        return guard(
            "list_pets",
            lambda: ok(
                client.request(
                    "GET",
                    "/api/v1/pets",
                    params={"page": page, "pageSize": page_size, "species": species, "status": status, "sortBy": sort_by, "order": order},
                    tool="list_pets",
                )
            ),
        )

    # ---------------- 工具 2：单只查询 ----------------
    @mcp.tool(description="按宠物档案 ID 查询单只宠物的完整档案（含主人、病情、医生、住院状态）。")
    async def get_pet(
        pet_id: Annotated[str, Field(min_length=1, max_length=32, description="宠物档案 ID，形如 PET-000001")],
    ) -> str:
        return guard("get_pet", lambda: ok(client.request("GET", f"/api/v1/pets/{pet_id}", tool="get_pet")))

    # ---------------- 工具 3：建档 ----------------
    @mcp.tool(description="新增宠物档案。name/species/ownerName/ownerPhone 必填，其余可选；成功返回新建档案（含分配到的 petId）。")
    async def create_pet(
        name: Annotated[str, Field(min_length=1, max_length=32, description="宠物名，必填")],
        species: Annotated[Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"], Field(description="宠物种类，必填")],
        owner_name: Annotated[str, Field(min_length=1, max_length=32, description="主人姓名，必填")],
        owner_phone: Annotated[str, Field(min_length=6, max_length=20, description="主人联系电话，必填")],
        disease: Annotated[str | None, Field(max_length=200, description="初步诊断/主诉，可选")] = None,
        doctor: Annotated[str | None, Field(max_length=32, description="接诊医生，可选")] = None,
        breed: Annotated[str | None, Field(max_length=32, description="品种，如 金毛/英短，可选")] = None,
        gender: Annotated[Literal["公", "母", "未知"] | None, Field(description="性别，可选")] = None,
        age_months: Annotated[int | None, Field(ge=0, le=400, description="月龄，0-400")] = None,
        status: Annotated[Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"] | None, Field(description="就诊状态，默认待就诊")] = None,
    ) -> str:
        body = {
            "name": name,
            "species": species,
            "ownerName": owner_name,
            "ownerPhone": owner_phone,
            "disease": disease,
            "doctor": doctor,
            "breed": breed,
            "gender": gender,
            "ageMonths": age_months,
            "status": status,
        }
        body = {k: v for k, v in body.items() if v is not None}
        return guard("create_pet", lambda: ok(client.request("POST", "/api/v1/pets", body=body, tool="create_pet")))

    # ---------------- 工具 4：全文检索 ----------------
    @mcp.tool(description="跨字段全文检索宠物档案（空格分词、AND 语义）。适合“找肠胃炎的狗”这类模糊查询。")
    async def search_pets(
        q: Annotated[str, Field(min_length=1, max_length=100, description="检索词，多个词用空格分隔")],
    ) -> str:
        return guard("search_pets", lambda: ok(client.request("GET", "/api/v1/pets/search", params={"q": q}, tool="search_pets")))

    # ---------------- 工具 5：按主人查 ----------------
    @mcp.tool(description="按主人姓名或电话查其名下所有宠物，两个参数至少给一个。")
    async def find_pets_by_owner(
        owner_name: Annotated[str | None, Field(max_length=32, description="主人姓名，可选")] = None,
        owner_phone: Annotated[str | None, Field(max_length=20, description="主人电话，可选")] = None,
    ) -> str:
        if not owner_name and not owner_phone:
            return fail("VALIDATION_ERROR", "owner_name 与 owner_phone 至少提供一个")
        params = {"ownerName": owner_name, "ownerPhone": owner_phone}
        return guard("find_pets_by_owner", lambda: ok(client.request("GET", "/api/v1/pets/by-owner", params=params, tool="find_pets_by_owner")))

    # ---------------- 工具 6：病历 ----------------
    @mcp.tool(description="读取某只宠物的全部历史病历（按时间倒序）。")
    async def list_medical_records(
        pet_id: Annotated[str, Field(min_length=1, max_length=32, description="宠物档案 ID")],
    ) -> str:
        return guard("list_medical_records", lambda: ok(client.request("GET", f"/api/v1/pets/{pet_id}/records", tool="list_medical_records")))

    # ---------------- 工具 7：追加病历 ----------------
    @mcp.tool(description="为宠物追加一条就诊病历（诊断/症状/处置/处方/体重/体温/本次收费）。")
    async def add_medical_record(
        pet_id: Annotated[str, Field(min_length=1, max_length=32, description="宠物档案 ID")],
        doctor: Annotated[str, Field(min_length=1, max_length=32, description="接诊医生，必填")],
        diagnosis: Annotated[str, Field(min_length=1, max_length=200, description="诊断结论，必填")],
        symptoms: Annotated[str | None, Field(max_length=200, description="症状描述，可选")] = None,
        treatment: Annotated[str | None, Field(max_length=300, description="处置方案，可选")] = None,
        prescription: Annotated[list[str] | None, Field(description="处方药品列表，可选")] = None,
        weight_kg: Annotated[float | None, Field(gt=0, le=200, description="体重（公斤），可选")] = None,
        temperature: Annotated[float | None, Field(ge=30, le=45, description="体温（摄氏度），可选")] = None,
        charge: Annotated[float | None, Field(ge=0, description="本次收费金额，可选")] = None,
    ) -> str:
        body = {
            "doctor": doctor,
            "diagnosis": diagnosis,
            "symptoms": symptoms,
            "treatment": treatment,
            "prescription": prescription or None,
            "weightKg": weight_kg,
            "temperature": temperature,
            "charge": charge,
        }
        body = {k: v for k, v in body.items() if v is not None}
        return guard(
            "add_medical_record", lambda: ok(client.request("POST", f"/api/v1/pets/{pet_id}/records", body=body, tool="add_medical_record"))
        )

    # ---------------- 工具 8：收费 ----------------
    @mcp.tool(description="为宠物追加一笔收费明细（项目/分类/金额/经办医生）。")
    async def add_charge(
        pet_id: Annotated[str, Field(min_length=1, max_length=32, description="宠物档案 ID")],
        item: Annotated[str, Field(min_length=1, max_length=64, description="收费项目名称，必填")],
        category: Annotated[Literal["检查", "药品", "手术", "住院", "疫苗", "其他"], Field(description="收费分类，必填")],
        amount: Annotated[float, Field(gt=0, le=100000, description="金额（元），必须大于 0")],
        doctor: Annotated[str | None, Field(max_length=32, description="经办医生，可选")] = None,
    ) -> str:
        body = {"item": item, "category": category, "amount": amount, "doctor": doctor}
        body = {k: v for k, v in body.items() if v is not None}
        return guard("add_charge", lambda: ok(client.request("POST", f"/api/v1/pets/{pet_id}/charges", body=body, tool="add_charge")))

    # ---------------- 工具 9：单只汇总 ----------------
    @mcp.tool(description="某只宠物的费用与就诊汇总：总花费、病历条数、分类小计、最近一次就诊。")
    async def pet_summary(
        pet_id: Annotated[str, Field(min_length=1, max_length=32, description="宠物档案 ID")],
    ) -> str:
        return guard("pet_summary", lambda: ok(client.request("GET", f"/api/v1/pets/{pet_id}/summary", tool="pet_summary")))

    # ---------------- 工具 10：经营统计 ----------------
    @mcp.tool(description="医院经营统计：总收入、宠物数、种类分布、医生接诊排行、消费 TopN。")
    async def hospital_stats(
        top: Annotated[int, Field(ge=1, le=50, description="榜单条数，1-50，默认 5")] = 5,
    ) -> str:
        return guard("hospital_stats", lambda: ok(client.request("GET", "/api/v1/stats", params={"top": top}, tool="hospital_stats")))

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="宠物医院 MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="stdio（默认）或 http")
    parser.add_argument("--base-url", default=os.environ.get("PET_HOSPITAL_BASE_URL", DEFAULT_BASE_URL), help="宠物医院 REST 地址")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="后端超时秒数")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="失败重试次数")
    parser.add_argument("--host", default="127.0.0.1", help="http 传输监听地址")
    parser.add_argument("--port", type=int, default=8765, help="http 传输端口")
    args = parser.parse_args(argv)

    mcp = build_server(base_url=args.base_url, timeout=args.timeout, retries=args.retries)

    if args.transport == "http":
        kwargs: dict[str, Any] = {}
        sig = inspect.signature(mcp.run_streamable_http_async)
        if "host" in sig.parameters:
            kwargs["host"] = args.host
        if "port" in sig.parameters:
            kwargs["port"] = args.port
        asyncio.run(mcp.run_streamable_http_async(**kwargs))
    else:
        asyncio.run(mcp.run_stdio_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
