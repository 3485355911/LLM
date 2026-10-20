import configparser
import datetime
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
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断给定年份是否为闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "要判断的年份"},
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getChineseDate",
            "description": "换算公历日期的农历（阴历）日期、天干地支纪年和生肖，不传 date 时默认取今天",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "公历日期，格式 YYYY-MM-DD，如 2007-03-12"},
                },
            },
        },
    },
]


def getdate():
    # 调用本地 date/time 命令获取当前日期和时间
    return subprocess.run("date /t & time /t", shell=True, capture_output=True, text=True).stdout.strip()


def isLeapYear(year):
    # 用 Python 计算该年份是否为闰年
    year = int(year)
    return "闰年" if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else "平年"


# 1900-2100 年农历数据表：低4位为闰月月份(0表示无闰月)，其余位表示各月大小月(1为30天)
LUNAR_INFO = [
    0x04bd8, 0x04ae0, 0x0a570, 0x054d5, 0x0d260, 0x0d950, 0x16554, 0x056a0, 0x09ad0, 0x055d2,
    0x04ae0, 0x0a5b6, 0x0a4d0, 0x0d250, 0x1d255, 0x0b540, 0x0d6a0, 0x0ada2, 0x095b0, 0x14977,
    0x04970, 0x0a4b0, 0x0b4b5, 0x06a50, 0x06d40, 0x1ab54, 0x02b60, 0x09570, 0x052f2, 0x04970,
    0x06566, 0x0d4a0, 0x0ea50, 0x06e95, 0x05ad0, 0x02b60, 0x186e3, 0x092e0, 0x1c8d7, 0x0c950,
    0x0d4a0, 0x1d8a6, 0x0b550, 0x056a0, 0x1a5b4, 0x025d0, 0x092d0, 0x0d2b2, 0x0a950, 0x0b557,
    0x06ca0, 0x0b550, 0x15355, 0x04da0, 0x0a5b0, 0x14573, 0x052b0, 0x0a9a8, 0x0e950, 0x06aa0,
    0x0aea6, 0x0ab50, 0x04b60, 0x0aae4, 0x0a570, 0x05260, 0x0f263, 0x0d950, 0x05b57, 0x056a0,
    0x096d0, 0x04dd5, 0x04ad0, 0x0a4d0, 0x0d4d4, 0x0d250, 0x0d558, 0x0b540, 0x0b6a0, 0x195a6,
    0x095b0, 0x049b0, 0x0a974, 0x0a4b0, 0x0b27a, 0x06a50, 0x06d40, 0x0af46, 0x0ab60, 0x09570,
    0x04af5, 0x04970, 0x064b0, 0x074a3, 0x0ea50, 0x06b58, 0x055c0, 0x0ab60, 0x096d5, 0x092e0,
    0x0c960, 0x0d954, 0x0d4a0, 0x0da50, 0x07552, 0x056a0, 0x0abb7, 0x025d0, 0x092d0, 0x0cab5,
    0x0a950, 0x0b4a0, 0x0baa4, 0x0ad50, 0x055d9, 0x04ba0, 0x0a5b0, 0x15176, 0x052b0, 0x0a930,
    0x07954, 0x06aa0, 0x0ad50, 0x05b52, 0x04b60, 0x0a6e6, 0x0a4e0, 0x0d260, 0x0ea65, 0x0d530,
    0x05aa0, 0x076a3, 0x096d0, 0x04afb, 0x04ad0, 0x0a4d0, 0x1d0b6, 0x0d250, 0x0d520, 0x0dd45,
    0x0b5a0, 0x056d0, 0x055b2, 0x049b0, 0x0a577, 0x0a4b0, 0x0aa50, 0x1b255, 0x06d20, 0x0ada0,
    0x14b63, 0x09370, 0x049f8, 0x04970, 0x064b0, 0x168a6, 0x0ea50, 0x06b20, 0x1a6c4, 0x0aae0,
    0x0a2e0, 0x0d2e3, 0x0c960, 0x0d557, 0x0d4a0, 0x0da50, 0x05d55, 0x056a0, 0x0a6d0, 0x055d4,
    0x052d0, 0x0a9b8, 0x0a950, 0x0b4a0, 0x0b6a6, 0x0ad50, 0x055a0, 0x0aba4, 0x0a5b0, 0x052b0,
    0x0b273, 0x06930, 0x07337, 0x06aa0, 0x0ad50, 0x14b55, 0x04b60, 0x0a570, 0x054e4, 0x0d160,
    0x0e968, 0x0d520, 0x0daa0, 0x16aa6, 0x056d0, 0x04ae0, 0x0a9d4, 0x0a2d0, 0x0d150, 0x0f252,
    0x0d520,
]

GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
ANIMALS = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
CN_MONTH = "正二三四五六七八九十冬腊"
CN_DAY_TENS = "初十廿三"
CN_DAY_UNITS = "日一二三四五六七八九十"


def _leap_month(y):
    return LUNAR_INFO[y - 1900] & 0xf


def _month_days(y, m):
    return 30 if LUNAR_INFO[y - 1900] & (0x10000 >> m) else 29


def _leap_days(y):
    return (30 if LUNAR_INFO[y - 1900] & 0x10000 else 29) if _leap_month(y) else 0


def _year_days(y):
    days = 348 + sum(1 for i in range(12) if LUNAR_INFO[y - 1900] & (0x8000 >> i))
    return days + _leap_days(y)


def _solar_to_lunar(d):
    offset = (d - datetime.date(1900, 1, 31)).days
    year = 1900
    while year < 2100 and offset >= _year_days(year):
        offset -= _year_days(year)
        year += 1
    leap = _leap_month(year)
    is_leap = False
    month = 1
    while month <= 12:
        days = _leap_days(year) if is_leap else _month_days(year, month)
        if offset < days:
            break
        offset -= days
        if is_leap:
            is_leap = False
            month += 1
        elif month == leap:
            is_leap = True
        else:
            month += 1
    return year, month, offset + 1, is_leap


def getChineseDate(date=None):
    # 用内置农历数据表换算公历日期（缺省为今天）的阴历日期，并给出干支纪年和生肖
    solar = datetime.date.fromisoformat(date) if date else datetime.date.today()
    year, month, day, is_leap = _solar_to_lunar(solar)
    month_name = ("闰" if is_leap else "") + CN_MONTH[month - 1] + "月"
    if day == 10:
        day_name = "初十"
    elif day == 20:
        day_name = "二十"
    elif day == 30:
        day_name = "三十"
    else:
        day_name = CN_DAY_TENS[day // 10] + CN_DAY_UNITS[day % 10]
    ganzhi = GAN[(year - 4) % 10] + ZHI[(year - 4) % 12]
    animal = ANIMALS[(year - 4) % 12]
    return (
        f"阳历（公历）：{solar}\n"
        f"阴历（农历）：{month_name}{day_name}\n"
        f"天干地支：{ganzhi}年\n"
        f"生肖：{animal}"
    )


messages = []
while True:
    question = input("请输入问题（直接回车退出）：")
    if not question.strip():
        break
    messages.append({"role": "user", "content": question})
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
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"] or "{}")
            if name == "getdate":
                result = getdate()
            elif name == "isLeapYear":
                result = isLeapYear(args["year"])
            elif name == "getChineseDate":
                result = getChineseDate(args.get("date"))
            print(f"[{name}] {result}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
