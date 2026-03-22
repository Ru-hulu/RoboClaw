# RoboClaw Agent 开发指南

---

## Part 1: 终极目标

用自然语言控制任何机器人。用户不碰代码、不看文档、不配环境。

- **L0** — 没有机器人？打开就能在仿真里对话操控。
- **L1** — 刚买了机械臂？几句话完成连接、校准、让它动起来。
- **L2** — 想做复杂任务？对话组合出抓取、搬运等技能。
- **L3** — 做科研？对话驱动数据采集、训练、部署、监督，完整闭环。
- 接入新机器人不写代码，对话描述硬件，Agent 生成 adapter。
- 借鉴 LeRobot 的 dataset 格式和训练范式，自己实现，不引入外部依赖。
- 内置 ACT、Diffusion Policy 等主流算法，对话选择和调参。
- 仿真到真机无缝切换。每个本体自带安全约束，框架强制执行。

> 完整产品版图见 `docs/product-vision.md`，竞品分析见 `docs/competitive-analysis.md`。

---

## Part 2: TODO

> Claude B (loop) 按此列表工作。完成后标记 ✅，遇到阻塞标记 🚫。

### 当前批次

- [ ] 1. Schema 精简：删除 ControlGroups、SafetyZones、SafetyBoundaries、ResourceOwnership、FailureDomains、CompensationSpec、IdempotencyMode；简化 Procedure 系统（去掉补偿/回滚/幂等）
- [ ] 2. 获取 SO101 URDF 模型：从 LeRobot 或官方获取，放入 `simulation/models/so101.urdf`
- [ ] 3. A4 仿真验收：没有硬件，对话进入仿真，虚拟臂运动（依赖 #2）
- [ ] 4. A1 夹爪验收：在 4090-zhaobo 上对话控制 SO101 夹爪开合，摄像头确认。Agent 已可对话，需排查 ROS2 控制面启动问题
- [ ] 5. A6 采集验收：对话引导采集 10 episode（依赖 #4）
- [ ] 6. A7 训练验收：对话选算法、训练 ACT、checkpoint 保存（依赖 #5）



---

## Part 3: 工作规范

### 写代码

- Claude Code 写代码。写完后用 `/codex-review` 让 Codex 审查，根据审查结果修复问题。
- 每次结构性改动后，跑 `bash scripts/embodied_lines.sh` 并与上次对比。如果行数增长，必须给出理由或重构到不涨。向用户汇报 before/after。

### 代码规范

- 框架代码放 `roboclaw/embodied/`，用户资产放 `~/.roboclaw/workspace/embodied/`。
- 不在通用层硬编码具体本体。本体特定逻辑只能在 `builtins/<id>.py`、manifest、profile、bridge 里。
- 生产框架代码保持英文。
- 最小化代码量。不引入新抽象，除非它消除的代码比引入的更多。
- RoboClaw 对用户的对话必须保持高层次和通用化。不暴露串口路径、底层协议细节、内部技术实现。用户应无感地完成操作。

### 验证

- 本地：`python -m pytest tests/ -x -q`
- 远程 Docker：按 memory 中存储的流程执行（`reference_remote_validation.md`）
- **每次代码改动后，必须按 `docs/acceptance-test.md` 执行验收测试。** Claude Code 扮演小白用户，自由对话 RoboClaw，通过摄像头验证夹爪开合。测试通过不算验收，对话走通才算。

> 验收测试案例详见 `docs/acceptance-test.md`（A1 夹爪开合 / A4 仿真体验 / A6 采集 episode / A7 训练 ACT）。
