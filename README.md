# 考研真题搭配 → 墨墨每日入库

本目录 `maimemo-daily/` 配合 GitHub Actions 每天日本时间约 08:30（北京时间 07:30）自动写入 **10 个经过真题原文核实的英文搭配** 到墨墨背单词。

## 唯一需要手动完成的授权

1. 打开 [仓库 Actions Secrets](https://github.com/xinhang725-code/ankiweb--codex--notion/settings/secrets/actions)，点 **New repository secret**。
2. 名称填 `MAIMEMO_TOKEN`，值粘贴你在墨墨官方开放 API 页面获取的 Token。聊天中已公开过的旧 Token 建议先撤销、换新。
3. 打开 [Actions](https://github.com/xinhang725-code/ankiweb--codex--notion/actions/workflows/maimemo-daily.yml)，点 **Run workflow** 运行一次并查看日志。之后每日自动运行。

程序通过官方 API 查询词典、优先匹配整条短语，否则依附核心单词，自动创建类型为「固定搭配」的助记；若完整短语不在词典中，还将创建自定义考研释义和来自真题的例句，附中文义、来源及易错辨析。同时在专用云词本「考研真题高频搭配」收录可识别的词项。公开 API 不支持创建全新的底层词典 voc_id；遇到词典没有整条搭配时不会伪造独立词典项，而是将自定义释义、助记、例句挂在已有的核心词上。若连核心词都不存在，程序会如实报告并跳过，不会错误宣称已写入。

数据来源：`maimemo-daily/data/seed.json` 是从你做过的真题提取并核验的种子；`maimemo-daily/data/queue.json` 可由每天的 ChatGPT 自动任务继续补充。成功写入的记录自动存到 `data/state.json`，避免重复。种子会用完；后续需要继续填充有据可查的真题搭配。任务不修改你的学习计划。

**不会公开 Token，也不会把 Token 存在仓库文件里。** 若 API 授权失效、候选不足或网络失败，将报告错误而不会虚报写入成功。

官方接口文档： https://open.maimemo.com/ 。