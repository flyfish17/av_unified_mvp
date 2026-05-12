# Mac 部署 SOP

> **状态**：占位文档。Mac 是开发 + 演示主机，完整经验散在 `DEVELOPMENT_PLAN.md` 多个章节，待提炼。

## 当前已有的 Mac 部署知识在哪

1. **快速启动**：根目录 `README.md` § 快速开始 — 一次性准备 + `./start.command` 双击启动
2. **架构 + 模块**：`README.md` § 架构 / `DEVELOPMENT_PLAN.md` § 2 目标架构（六层）
3. **多端 RAM 自适应**：`DEVELOPMENT_PLAN.md` § 2026-05-11–12 多端部署 — `<10GB` Mac 自动降 light 档（LLM 改 qwen3.5:2b-q4_K_M + audio 改本地 SenseVoice + 关 RTSP）
4. **常见坑**：同一节列了 10 条（TCC 权限按"启动 app"颗粒、brew cask sudo、ollama formula vs cask、mosquitto 默认 conf 缺失 等）
5. **8GB / 16GB 配置实测**：同一节 § 关键经验 第 10 条 — light 套餐内存画像
6. **支持的环境**：airblue M2/16GB、8GB Air、Mac Mini M2 16GB 都已实测

## 何时单独抽这份 SOP

下一个非紧急 sprint。当 Mac 部署 SOP 真要独立成文（比如多名 Mac 用户接手），从 `DEVELOPMENT_PLAN.md` 提炼为 step-by-step。

目前对开发者：直接看 `start.command` 源码 + `DEVELOPMENT_PLAN.md` § 2026-05-11–12 即可。
