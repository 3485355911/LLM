import configparser
import json
import subprocess
import time
import requests

config = configparser.ConfigParser()
config.read("config.ini")
cfg = config["llm"]

tools = [
    {
        "type": "function",
        "function": {
            "name": "getdate",
            "description": "获取当前的时间和日期",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def getdate():
    # 调用本地 date/time 命令获取当前日期和时间
    return subprocess.run("date /t & time /t", shell=True, capture_output=True, text=True).stdout.strip()


messages = [{"role": "user", "content": input("请输入问题：")}]
while True:
    resp = requests.post(
        f"{cfg['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json={
            "model": cfg["model_name"],
            "messages": messages,
            "tools": tools,
            "stream": True,
        },
        stream=True,
    )

    reply = ""
    tool_calls = {}
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            data = line[5:].strip()
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0]["delta"]
            if delta.get("content"):
                for ch in delta["content"]:
                    print(ch, end="", flush=True)
                    time.sleep(0.02)
                reply += delta["content"]
            for tc in delta.get("tool_calls", []):
                acc = tool_calls.setdefault(
                    tc["index"],
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                acc["id"] = acc["id"] or tc.get("id")
                acc["function"]["name"] += tc["function"].get("name") or ""
                acc["function"]["arguments"] += tc["function"].get("arguments") or ""
    print()

    if not tool_calls:
        messages.append({"role": "assistant", "content": reply})
        break

    calls = list(tool_calls.values())
    messages.append({"role": "assistant", "content": reply or None, "tool_calls": calls})
    for call in calls:
        result = getdate()
        print(f"[getdate] {result}")
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
