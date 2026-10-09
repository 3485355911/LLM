import configparser
import json
import time
import requests

config = configparser.ConfigParser()
config.read("config.ini")
cfg = config["llm"]

messages = []
while True:
    messages.append({"role": "user", "content": input("请输入问题：")})
    resp = requests.post(
        f"{cfg['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        json={
            "model": cfg["model_name"],
            "messages": messages,
            "stream": True,
        },
        stream=True,
    )

    reply = ""
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data:"):
            data = line[5:].strip()
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0]["delta"]
            if "content" in delta:
                for ch in delta["content"]:
                    print(ch, end="", flush=True)
                    time.sleep(0.02)
                reply += delta["content"]
    print()
    messages.append({"role": "assistant", "content": reply})
