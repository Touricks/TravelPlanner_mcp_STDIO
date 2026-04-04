# Project

> This project uses [Sentinel](docs/getting-started.md) for AI-managed documentation.

当前作品的问题包括：<problem>1.对用户画像收集不到位，除了起始时间等记录在userProfile/下的内容，还需要考虑travelPace（每天去几个景点）以及具体的旅游路线框架（比如用户想在这段时间希望参观的POIs,e.g.红杉公园）2. Agent对列举的POIs的时间安排没有围栏：自然景色不应该放到19:00之后，有人工参与的项目不应该放到16:00之后（下班了）。3.对餐厅和酒店的安排没有指引，且安排时间和地点有问题，Agent应该先生成行程，然后根据行程安排推荐餐厅和酒店。4.可视化模版可读性差，需要生成四节内容：行程安排/餐厅推荐清单/酒店推荐清单/注意事项</problem> <solution>要解决问题1，我们可以参考@03-memory_01.md为这个任务创建记忆系统，不一定需要用RAG，但是合适的数据库和hook是必要的。要解决问题2，我们考虑使用/codex:rescue 和/codex:result来辅助web search搜集POIs信息，并在生成yaml/json计划后通过/codex:review检查是否存在时间重叠和不合理景点安排。 要解决问题3，我觉得需要更清晰的workflow，在步骤二的yaml生成后调用codex协助搜集餐厅/酒店； 要解决问题4，我觉得需要通过notion mcp + playwright/computer use mcp去通过截屏的方式自主验证可视化效果，并通过codex审阅</solution> 