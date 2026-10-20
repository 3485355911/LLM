# practice02 — 带 Function Calling 的本地大模型交互客户端

基于 `requests` 流式调用大模型 `chat/completions` 接口，内置 3 个本地工具（日期、闰年、农历换算），支持多轮对话。

## 目录结构

```
practice02/
├── main.py        # 主程序
├── main.mmd       # Mermaid 架构图
└── config.ini     # 模型配置（需自备）
```

## 运行

```bash
pip install requests
py main.py
```

交互：直接输入问题；空行退出。

## 配置

`config.ini` 需要一个 `[llm]` 节：

```ini
[llm]
base_url = https://your-endpoint/v1
api_key  = sk-xxx
model_name = your-model
```

## 内置工具

| 工具 | 参数 | 实现方式 | 说明 |
|---|---|---|---|
| `getdate` | 无 | `subprocess` 调 `date /t & time /t` | 获取当前日期时间 |
| `isLeapYear` | `year` (int) | Python 公式 `year%4==0 and (year%100!=0 or year%400==0)` | 判断闰年 |
| `getChineseDate` | `date` (str, 可选, `YYYY-MM-DD`) | 内置 1900–2100 农历表 + 干支/生肖公式 | 阳历 → 阴历 + 天干地支 + 生肖 |

农历数据表 `LUNAR_INFO` 位于 `main.py` 中，无需额外依赖；干支/生肖公式以公元 4 年为基准：`(year - 4) % 10 / 12`。

## 交互流程

1. 用户输入 → 写入 `messages`。
2. 内层循环发 `chat/completions`（`tools` + `stream=true`），边收边打印；同时把流式 `tool_calls` 累积完整。
3. 无工具调用：写入 `assistant` 消息，回到外层等下一问。
4. 有工具调用：分发执行，把 `role=tool` 消息追加到 `messages`，回到内层继续请求模型（直到模型不再请求工具）。

## 架构图

见 [main.mmd](./main.mmd)，可粘贴到 [mermaid.live](https://mermaid.live) 或支持 Mermaid 的 Markdown 预览器渲染。

## 示例

```
请输入问题（直接回车退出）：今天是农历几月几日？属什么？
[getChineseDate] 阳历（公历）：2026-10-20
阴历（农历）：九月十一
天干地支：丙午年
生肖：马
今天是农历九月十一，丙午年（马年）。

请输入问题（直接回车退出）：2007年是闰年吗？三月十二日是农历？
[isLeapYear] 平年
[getChineseDate] 阳历（公历）：2007-03-12
阴历（农历）：正月廿三
天干地支：丁亥年
生肖：猪
2007 不是闰年。那天是农历正月廿三，丁亥猪年。

请输入问题（直接回车退出）：
EXIT_CODE=0
```
