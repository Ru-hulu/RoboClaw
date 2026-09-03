# RoboClaw 工具系统与 SAM3 运行机制指南

本文档以当前仓库实现为准，详细介绍 RoboClaw 工具从定义、注册到被 LLM 调用的完整链路，以及模拟定位、Hybrid A*、MPC 路径跟踪、OpenArm 和 SAM3 的使用方法。

> SAM3 说明：当前 MCP Tool 层只注册 `start_sam3_perception`、
> `get_sam3_perception_status` 和 `stop_sam3_perception` 三个进程生命周期
> Tool。推理 RPC 将由后续独立业务 Tool 调用，不属于生命周期 manager。
> 第 9 章中关于旧 lazy worker / one-shot 分割的细节属于历史设计材料，请以
> `robot_runtime/perception/sam3/README.md` 和代码为准。

阅读本文后，应该能够回答以下问题：

- RoboClaw 中一个工具定义在哪里，具体实现又在哪里？
- MCP Server、Agent、Tool Registry 和 `robot_runtime` 如何配合？
- 当前 13 个工具分别做什么、需要哪些输入、应该按什么顺序调用？
- 既然已经有 MCP，为什么 SAM3 还需要独立 worker？
- SAM3 是不是懒加载，多久会卸载，什么情况下需要重新加载？
- 新的机器人、场景物体或算法应该怎样封装成 Tool/MCP？

## 1. 整体架构

为兼容 GitHub、IDE、终端和不同 Markdown 渲染器，本文使用纯文本图，不使用 Mermaid。

```text
用户自然语言
    |
    v
AgentRuntime
    |  将消息和工具 JSON Schema 发给 LLM
    v
LLM 返回普通回答或 tool_calls
    |
    v
ToolRegistry
    |  根据 Agent 工具名找到 MCPToolAdapter
    v
MCPToolAdapter
    |  转换为 MCP call_tool 请求
    v
MCPClientRuntime
    |  通过 stdin/stdout 连接 FastMCP Server
    v
roboclaw_next/tools/mcp_server.py
    |  调用对应 builtin 工具
    v
roboclaw_next/tools/builtin/<name>/tool.py
    |  参数校验、返回 Schema、错误转换
    v
roboclaw_next/tools/builtin/<name>/program.py
    |  进程管理、算法适配、超时与生命周期
    v
robot_runtime
    |  ROS 节点 / C++ 规划器 / 控制算法 / 感知模型
    v
结构化结果回到 LLM
```

核心文件职责：

| 文件或目录 | 职责 |
| --- | --- |
| `roboclaw_next/tools/mcp_server.py` | 创建 FastMCP Server，构造共享管理器，注册全部工具 |
| `roboclaw_next/tools/builtin/*/tool.py` | 定义工具名、描述、参数、输出和 annotations |
| `roboclaw_next/tools/builtin/*/program.py` | 执行真实业务或管理进程生命周期 |
| `roboclaw_next/tools/mcp_runtime.py` | 启动并连接 stdio MCP Server，提供 `list_tools`/`call_tool` |
| `roboclaw_next/tools/mcp_adapter.py` | 将 MCP 工具包装成 Agent 可调用的 `AgentTool` |
| `roboclaw_next/tools/registry.py` | 管理 Agent 可见的工具并执行调用 |
| `roboclaw_next/agent/runtime.py` | 驱动 LLM、工具调用和结果回填循环 |
| `robot_runtime/` | 定位、规划、控制、机械臂和感知的具体实现 |

## 2. 工具如何定义、注册和调用

### 2.1 `tool.py` 定义 MCP 契约

每组工具提供一个 `register_*_tools()` 函数，并在其中使用 `@mcp.tool(...)`：

```python
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field


class ExampleResult(BaseModel):
    ok: bool
    message: str


def register_example_tools(mcp: FastMCP, manager: ExampleManager) -> None:
    @mcp.tool(
        name="run_example",
        title="Run Example",
        description="Explain when to call this tool and its prerequisites.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def run_example(
        value: Annotated[
            str,
            Field(min_length=1, description="Meaning and unit of this value."),
        ],
    ) -> ExampleResult:
        return ExampleResult.model_validate(await manager.run(value))
```

FastMCP 根据函数签名、`Annotated`、`Field` 和 Pydantic 返回模型生成 JSON Schema。LLM 看见的是工具名、描述和 Schema，而不是 Python 源码。

工具描述应该明确：

- 什么时候调用。
- 调用前置条件。
- 坐标系、单位和数据格式。
- 返回值代表什么。
- 工具不会执行哪些操作。
- 成功后通常调用哪个工具。

### 2.2 ToolAnnotations

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| `readOnlyHint` | 是否只读或只计算 | 状态查询、OpenArm FK/IK |
| `destructiveHint` | 是否可能终止或破坏状态 | `unload_sam3` 会结束 worker |
| `idempotentHint` | 相同参数重复调用是否基本等价 | 状态查询、重复 start/stop |
| `openWorldHint` | 是否访问开放互联网或不可控外部环境 | 当前机器人工具均为 `False` |

这些字段是行为提示，不代替文件权限、设备权限、ROS 权限或安全策略。

### 2.3 `program.py` 连接真实实现

```text
tool.py
  MCP 名称、输入输出 Schema、参数说明、错误契约

program.py
  进程状态、启动停止、超时、算法适配、结果转换

robot_runtime
  真实定位、规划、控制、运动学或神经网络推理
```

协议层保持轻量，可以让底层算法或启动方式在不破坏 MCP 接口的前提下迭代。

### 2.4 MCP Server 注册

`roboclaw_next/tools/mcp_server.py` 当前会：

```text
创建 FastMCP("RoboClaw Tool Server")
    |
    +-- MockLocalizationProcessManager
    |
    +-- PathTrackingProcessManager
    |      与定位工具共享同一个 localization manager
    |
    +-- Sam3WorkerProcessManager
    |
    +-- 注册定位、路径跟踪、Hybrid A*、OpenArm 和 SAM3 工具
```

共享定位 manager 很重要：路径跟踪在启动前可以确认由当前 MCP Server 管理的定位进程是否正在运行。

### 2.5 MCP 工具名和 Agent 工具名

MCP Server 暴露原始名称：

```text
segment_image_with_sam3
plan_hybrid_astar_path
start_mock_localization
```

示例客户端把 MCP Server 命名为 `roboclaw_tools`。`MCPToolAdapter` 为避免多个 Server 工具重名，会生成 Agent 名称：

```text
roboclaw_tools__segment_image_with_sam3
roboclaw_tools__plan_hybrid_astar_path
roboclaw_tools__start_mock_localization
```

用户不需要记忆这些前缀，LLM 会根据自然语言和工具描述自动选择。

## 3. 当前 13 个工具总览

| 分组 | 工具名 | 运行方式 | 主要结果或状态 |
| --- | --- | --- | --- |
| 模拟定位 | `start_mock_localization` | 启动 ROS 节点 | state、PID、退出码 |
| 模拟定位 | `get_mock_localization_status` | 查询 manager | state、PID、退出码 |
| 模拟定位 | `get_mock_localization` | 短生命周期 ROS Service Client | map-frame x/y/yaw |
| 模拟定位 | `stop_mock_localization` | 停止 ROS 节点 | stopped 状态 |
| 路径规划 | `plan_hybrid_astar_path` | 单次 C++ 子进程 | waypoint 和路径 JSON |
| 路径跟踪 | `start_path_tracking` | 启动 MPC ROS 节点 | state、PID、路径文件 |
| 路径跟踪 | `get_tracking_status` | 查询 manager | state、PID、退出码 |
| 路径跟踪 | `stop_path_tracking` | 停止 MPC 进程 | stopped 状态 |
| OpenArm | `get_openarm_ee_pose` | 进程内 FK | 末端位姿 |
| OpenArm | `plan_openarm_reach` | 进程内 IK | 关节轨迹和最终误差 |
| SAM3 | `start_sam3_perception` | 启动常驻感知服务 | state、PID、模型状态 |
| SAM3 | `get_sam3_perception_status` | 查询 manager | state、PID、模型状态 |
| SAM3 | `stop_sam3_perception` | 停止常驻感知服务 | stopped 状态 |

当前工具包含四种典型模式：

| 模式 | 代表工具 | 适用场景 |
| --- | --- | --- |
| 纯函数 | OpenArm FK/IK | 计算快、无外部进程、无长期资源 |
| 单次子进程 | Hybrid A* | 每次任务独立，运行后自然退出 |
| 受管理常驻进程 | 定位、MPC | ROS 节点需要持续发布、订阅或控制 |
| 受管理常驻感知服务 | SAM3 | 模型加载昂贵，进程和 GPU 状态需要复用 |

## 4. 模拟定位

代码：

- `roboclaw_next/tools/builtin/mock_localization/tool.py`
- `roboclaw_next/tools/builtin/mock_localization/program.py`
- `robot_runtime/localization/mock_localization/kinematic_node.py`

### 4.1 `start_mock_localization`

无输入。工具刷新状态后：

1. 如果进程已经运行，直接返回当前状态，不重复启动。
2. 尝试 source `/opt/ros/humble/setup.bash` 和仓库的 `install/setup.bash`。
3. 启动：

   ```text
   python -m robot_runtime.localization.mock_localization.kinematic_node
   ```

返回：

| 字段 | 含义 |
| --- | --- |
| `state` | `idle`、`running`、`stopped` 或 `failed` |
| `pid` | 子进程 PID |
| `return_code` | 进程退出码，运行时通常为空 |
| `message` | 生命周期说明 |

### 4.2 `get_mock_localization_status`

无输入。只查询进程状态，不启动定位。

### 4.3 `get_mock_localization`

无输入。调用：

```text
Service: /mock_localization/get_pose
Type:    roboclaw_interfaces/srv/GetMockLocalizationPose
```

返回示例：

```json
{
  "success": true,
  "frame_id": "map",
  "x": 1.2,
  "y": 0.8,
  "yaw": 0.0,
  "message": "Pose returned."
}
```

位置单位是米，yaw 是弧度。该工具临时创建 ROS Client，结束后销毁。如果服务不可用，默认约 3 秒超时并返回 `success=false`。

### 4.4 `stop_mock_localization`

无输入。先 terminate，最多等待 10 秒，必要时 kill；重复调用安全。

推荐流程：

```text
start_mock_localization
    |
get_mock_localization_status
    |
get_mock_localization
    |
执行规划或控制
    |
stop_mock_localization
```

## 5. Hybrid A* 路径规划

代码：

- `roboclaw_next/tools/builtin/hybrid_astar_planner/tool.py`
- `roboclaw_next/tools/builtin/hybrid_astar_planner/program.py`
- `robot_runtime/planning/hybrid_astar/`

### 5.1 `plan_hybrid_astar_path`

| 参数 | 单位 | 坐标系 | 含义 |
| --- | --- | --- | --- |
| `start_x` | 米 | `map` | 起点 X |
| `start_y` | 米 | `map` | 起点 Y |
| `start_yaw` | 弧度 | `map` | 起点航向 |
| `goal_x` | 米 | `map` | 目标 X |
| `goal_y` | 米 | `map` | 目标 Y |
| `goal_yaw` | 弧度 | `map` | 目标航向 |

如果用户没有给起点，应先调用 `get_mock_localization`，将 `x/y/yaw` 作为起点。

每次调用启动一个独立规划器。默认查找：

```text
install/lib/hybrid_astar/hybrid_astar_plan
robot_runtime/planning/hybrid_astar/build/hybrid_astar_plan
```

固定地图为：

```text
robot_runtime/planning/hybrid_astar/maps/empty_80x80.png
```

默认超时 30 秒。规划器 stdout 必须只输出一个机器可读 JSON，调试信息应进入 stderr。

返回示例：

```json
{
  "success": true,
  "frame_id": "map",
  "waypoints": [
    {"x": 1.0, "y": 2.0, "direction": "forward"},
    {"x": 1.1, "y": 2.0, "direction": "forward"}
  ],
  "waypoint_count": 2,
  "map_path": "/absolute/path/to/map.png",
  "path_file": "/absolute/path/to/latest_hybrid_astar_path.json",
  "planning_time_ms": 12.3,
  "message": "Path found."
}
```

注意：

- waypoint 是几何控制点，不是带时间参数的轨迹。
- waypoint 包含 `forward`/`reverse`，但不包含 yaw。
- MPC 会把它转换成保持运动方向的 B-Spline 参考位姿序列。
- 最新结果原子写入 `runtime_data/hybrid_astar/latest_hybrid_astar_path.json`。
- 规划开始和失败时也会写入失败结果，避免控制器误用旧路径。

构建方式：

```bash
colcon build --packages-up-to roboclaw_interfaces hybrid_astar
```

或 standalone：

```bash
cmake -S robot_runtime/planning/hybrid_astar \
  -B robot_runtime/planning/hybrid_astar/build
cmake --build robot_runtime/planning/hybrid_astar/build
```

## 6. MPC 路径跟踪

代码：

- `roboclaw_next/tools/builtin/path_tracking/tool.py`
- `roboclaw_next/tools/builtin/path_tracking/program.py`
- `robot_runtime/control/differential_drive_mpc/`

### 6.1 前置条件

`start_path_tracking` 不会自动定位，也不会自动规划。必须先满足：

1. 模拟定位状态为 `running`。
2. 存在有效的 Hybrid A* 路径 JSON。

### 6.2 `start_path_tracking`

可选参数：

```json
{
  "reference_path_file": "/absolute/path/to/hybrid_astar_path.json"
}
```

解析规则：

1. 绝对路径直接使用。
2. 相对路径相对于仓库根目录。
3. 不传时使用 `runtime_data/hybrid_astar/latest_hybrid_astar_path.json`。
4. 文件不存在或结构无效时不启动 MPC。

实际启动：

```text
python -m robot_runtime.control.differential_drive_mpc.ros_node \
  --ros-args \
  -p reference_path_file:=<resolved-path>
```

状态可能为 `idle`、`running`、`succeeded`、`failed`、`stopped`。

`get_tracking_status` 返回状态、PID、退出码、说明和当前路径文件。`stop_path_tracking` 先 terminate，10 秒后必要时 kill，重复调用安全。

### 6.3 完整导航流程

```text
1. start_mock_localization
          |
2. get_mock_localization
          |  得到 start_x/start_y/start_yaw
3. plan_hybrid_astar_path
          |  生成 latest_hybrid_astar_path.json
4. start_path_tracking
          |  MPC 读取路径并开始控制
5. get_tracking_status
          |  按任务需要查询
6. stop_path_tracking
          |
7. stop_mock_localization
```

Agent 应检查每一步的结构化结果，不能在定位或规划失败后继续启动 MPC。

## 7. OpenArm 正逆运动学

代码：

- `roboclaw_next/tools/builtin/openarm_reach/tool.py`
- `roboclaw_next/tools/builtin/openarm_reach/program.py`
- `robot_runtime/openarm_ik.py`

这两个工具是进程内纯计算，不启动 ROS/MuJoCo，不连接或控制真实电机。

### 7.1 `get_openarm_ee_pose`

```json
{
  "arm": "right",
  "joints": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
}
```

- `arm` 为 `right` 或 `left`。
- `joints` 可为 7 个机械臂关节，或带末尾夹爪值的 q8；FK 忽略夹爪。
- 返回 `[px, py, pz, qw, qx, qy, qz]`。
- 位置单位为米，四元数顺序为 `wxyz`，坐标系固定为 `arm_origin`。

### 7.2 `plan_openarm_reach`

```json
{
  "arm": "right",
  "joints": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
  "x": 0.35,
  "y": -0.15,
  "z": 0.30
}
```

工具计算当前末端姿态，使用目标 XYZ 并保持当前 orientation，执行 IK 迭代，返回：

| 字段 | 含义 |
| --- | --- |
| `ok` | 最终误差是否进入容差 |
| `failure_reason` | `converged` 或 `max_steps` |
| `final_error_m` | 最终位置误差，单位米 |
| `target_pose` | 完整目标位姿 |
| `dt` | 轨迹采样周期 |
| `points` | 每个时刻的关节值和末端位姿 |

如果后续需要驱动真实机械臂，应新增独立“轨迹执行工具”，不要让 `plan_openarm_reach` 同时规划和执行。

## 8. 为什么有 MCP 还需要 SAM3 worker

MCP 和 worker 解决不同问题：

```text
MCP
  解决：工具叫什么、参数是什么、怎样发现、怎样调用、怎样返回

SAM3 worker
  解决：在哪里加载模型、怎样占用/释放 GPU、怎样隔离依赖和故障
```

完整关系：

```text
LLM
  |
MCP tool: segment_image_with_sam3
  |
Sam3WorkerProcessManager
  |
隔离 Python worker
  |
官方 SAM3 + PyTorch + CUDA
  |
GPU
```

技术上可以直接在公共 MCP Server 中导入 torch 并加载模型，但会产生以下问题：

1. SAM3 的 Python/PyTorch/CUDA 依赖会污染主 MCP 环境。
2. SAM3 OOM、崩溃或卡死可能使定位、规划等全部工具断开。
3. 关闭模型时，进程内 `del model` 和 `torch.cuda.empty_cache()` 不一定释放 CUDA context 和全部 allocator 状态。
4. 为彻底释放 GPU 而关闭 MCP Server，会同时关闭所有机器人工具。
5. MCP Server 启动就加载模型会增加启动时间并长期占用约数 GiB 显存。

独立 worker 带来的边界：

- MCP Server 保持轻量，不导入 torch。
- 通过 `ROBOCLAW_SAM3_PYTHON` 使用独立环境。
- worker 退出时由操作系统销毁 CUDA context，显存释放更可靠。
- SAM3 错误转换成稳定结果，不破坏 MCP stdio 连接。
- 可以单独 `unload_sam3`，定位和规划工具继续工作。
- manager 可以串行化请求，避免多个请求同时修改 `Sam3Processor` 状态。
- 状态锁独立于请求串行锁，推理过程中仍可查询 `busy` 或主动卸载。

所以，MCP 是接口/控制层，worker 是模型执行/资源层，两者不是重复关系。

## 9. SAM3 工具与运行时

### 9.1 先看结论：当前采用什么方案

当前实现是“FastMCP Tool + MCP 进程内管理器 + 懒加载 SAM3 子 worker”，不是每次调用都重新加载，也不是独立的机器级常驻服务。

```text
LLM / Agent
    |
    | MCP Tool 调用
    v
FastMCP Server
    |
    | Python 方法调用
    v
Sam3WorkerProcessManager
    |
    | 有界 JSON Lines 协议
    v
SAM3 子 worker
    |
    | 官方 SAM3 推理接口
    v
GPU 模型 + 本地结果文件
```

模型的实际行为是：

1. MCP Server 启动时只创建轻量 manager，不加载 SAM3，也不占用 SAM3 显存。
2. 第一次调用 `segment_image_with_sam3` 时启动子 worker、校验源码和权重，然后加载模型。
3. 推理完成后模型继续驻留 GPU，默认保留 120 秒。
4. 120 秒内再次调用会复用同一个 worker 和同一份模型，不重新加载。
5. 从最后一次推理完成开始，连续空闲 120 秒后，worker 自动退出并释放显存。
6. 调用 `unload_sam3`、MCP Server 退出或 worker 异常时也会释放模型；下一次分割再重新加载。

因此它更准确地说是“按需启动、短期常驻、空闲回收”，而不是“每次请求加载并立即释放”。

相关代码：

| 层 | 路径 | 职责 |
| --- | --- | --- |
| MCP Tool 契约 | `roboclaw_next/tools/builtin/sam3_segmentation/tool.py` | 定义三个生命周期 Tool |
| 常驻感知服务 manager | `roboclaw_next/tools/builtin/sam3_segmentation/program.py` | 启动、状态查询和停止进程 |
| SAM3 Service | `robot_runtime/perception/sam3/service.py` | 启动并看护模型 Worker；RPC 接口暂未实现 |
| Worker 客户端 | `robot_runtime/perception/sam3/worker_client.py` | 管理 Worker 子进程和 JSON Lines 通信 |
| SAM3 推理 Worker | `robot_runtime/perception/sam3/worker.py` | 加载模型、执行推理并保持模型常驻 |
| SAM3 推理适配 | `robot_runtime/perception/sam3/` | 输入校验、官方模型调用和结果落盘 |

官方 SAM3 源码、训练代码和权重不进入 RoboClaw Git。仓库只保存推理适配层，外部 checkout 与 checkpoint 通过环境变量接入。

### 9.2 当前 SAM3 Tool

| Tool | 输入 | 是否加载模型 | 用途 |
| --- | --- | --- | --- |
| `start_sam3_perception` | 无 | 是；由常驻服务加载 | 启动 SAM3 perception service |
| `get_sam3_perception_status` | 无 | 否 | 查看进程状态、PID 和模型加载状态 |
| `stop_sam3_perception` | 无 | 否；只会停止 | 停止 SAM3 perception service |

这三个 Tool 共用同一个 `Sam3PerceptionManager`，只管理同一个常驻服务
进程，不接收 Prompt，也不执行推理 RPC。

#### `get_sam3_status` 的特点

- 不启动 worker。
- 不加载模型。
- 不延长 120 秒空闲期限。
- 推理正在执行时立即返回 `busy`，不等待推理完成。
- worker 未启动或已经回收时返回 `stopped` 和空 PID。

主要字段：

| 字段 | 含义 |
| --- | --- |
| `state` | `stopped`、`starting`、`ready` 或 `busy` |
| `pid` | 当前 worker PID；未运行时为 `null` |
| `current_request_id` | 正在推理的请求 ID |
| `last_activity_at` | 最近一次状态活动时间 |
| `idle_timeout_sec` | 当前空闲回收时间 |
| `load_duration_ms` | 本轮 worker 的模型加载耗时 |
| `message` | 面向操作人员的状态说明 |

#### `unload_sam3` 的特点

- 立即停止 worker，并释放该 worker 持有的模型显存。
- 如果当前正在推理，会中断该请求并等待进程清理完成。
- 已经写完的 `result.json`、mask 和 overlay 不会删除。
- 重复调用安全；worker 已停止时仍返回 `stopped`。

### 9.3 `segment_image_with_sam3` 参数

| 参数 | 约束 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `image_path` | 允许目录内的 JPEG、PNG 或 WebP | 必填 | 要处理的本地单张图片 |
| `text_prompt` | 1 到 256 字符 | 必填 | 要寻找的对象或短语，如 `red cup` |
| `confidence_threshold` | 0 到 1 的有限浮点数 | `0.5` | 结果保留阈值 |

当前 Tool 只处理本地单张图片，不处理视频，也不直接订阅 ROS Image Topic。ROS 相机图像需要先由其他节点或工具保存到允许目录，再把文件路径传入。

调用示例：

```json
{
  "image_path": "/data/robot_images/frame.png",
  "text_prompt": "red cup",
  "confidence_threshold": 0.5
}
```

### 9.4 threshold 到底是什么意思

这里的 threshold 指 `confidence_threshold`，也就是 SAM3 候选实例的最低保留分数：

```text
保留实例的条件：score >= confidence_threshold
```

假设 SAM3 对 `red cup` 返回三个候选：

| 候选 | score | threshold=0.5 时 |
| --- | ---: | --- |
| A | 0.82 | 保留 |
| B | 0.57 | 保留 |
| C | 0.31 | 丢弃 |

threshold 越低，通常召回越高，能留下更多候选，但误检、mask 数量、CPU/GPU 后处理和输出文件也可能增加。threshold 越高，结果更严格、更少，但可能漏掉遮挡、小尺寸或不典型目标。

建议从以下范围开始：

| threshold | 倾向 | 适合场景 | 风险 |
| ---: | --- | --- | --- |
| `0.2–0.3` | 高召回 | 初次探索、小目标、遮挡目标 | 误检和候选数量增加 |
| `0.5` | 平衡 | 默认生产起点 | 某些困难目标可能漏检 |
| `0.7–0.9` | 高精度 | 只接受高置信实例 | 漏检明显增加 |
| `0.0` | 保留全部候选 | 仅用于诊断 | 可能增加显存压力和输出量 |

需要注意：

- `score` 是模型针对当前图片与 prompt 给出的匹配分数，不是经过严格概率校准的“真实正确率”。
- 不同图片、prompt 或模型版本之间，不应只凭 score 绝对值做横向结论。
- 没有任何实例达到 threshold 时，调用仍然成功，只是 `instance_count=0`；这不是运行错误。
- 当前实现先把 threshold 传给官方 processor，在全分辨率 mask 插值前过滤候选；RoboClaw 规范化结果时还会再次检查 score。
- 在 8 GB GPU 上不建议无必要地使用 `0.0`，因为保留全部候选可能增加 mask 插值和输出阶段的显存压力。

实用调参顺序：

1. 先使用默认 `0.5`。
2. 如果明显漏检，将其降到 `0.3`，同时查看 overlay 是否出现误检。
3. 如果误检太多，将其提高到 `0.6` 或 `0.7`。
4. threshold 调整后仍不理想时，优先改进 `text_prompt`，例如把 `cup` 改成 `red cup`，而不是无限降低阈值。
5. 对固定相机和固定任务，用一组代表性图片确定阈值，不要只根据单张图片决定。

### 9.5 一次分割请求如何执行

```text
segment_image_with_sam3
    |
    | 1. 校验参数并进入串行请求队列
    v
检查 worker
    |
    +-- worker 不存在 --> 启动进程 --> 校验源码/权重 --> 加载模型
    |
    +-- worker ready --> 直接复用
    |
    | 2. 发送 request_id / image_path / prompt / threshold
    v
SAM3 worker
    |
    | 3. 校验允许目录、格式、大小和像素数
    | 4. 读取 RGB 图片并计算输入 SHA-256
    | 5. set_image + set_text_prompt
    | 6. 按 threshold 过滤并复制 masks / boxes / scores 到 CPU
    | 7. 写入隐藏临时目录，再原子重命名
    v
MCP 返回轻量元数据和 artifact 路径
```

输入保护包括：

- 路径必须位于 `ROBOCLAW_SAM3_INPUT_ROOTS` 允许范围内。
- 只接受 JPEG、PNG 或 WebP。
- 单文件最大 50 MiB。
- 解码后最多 4000 万像素。
- prompt 不允许为空，最长 256 字符。
- threshold 必须是 0 到 1 的有限数值。

MCP 不直接返回庞大的 mask 数组或 base64 图片，而是返回实例元数据和本地 artifact 路径，避免撑大 Tool 响应。

### 9.6 worker 状态机与重新加载条件

```text
MCP Server 启动
    |
[stopped]  manager 存在；worker 不存在；模型未加载
    |
    | 第一次 segment_image_with_sam3
    v
[starting] 启动 worker；校验依赖；加载模型
    |
    | 收到 ready 协议消息
    v
[ready]    模型驻留 GPU
    |
    | 收到分割请求
    v
[busy]     串行执行一次推理
    |
    | 推理完成
    v
[ready]    从完成时刻开始 120 秒空闲计时
    |
    | 连续空闲 120 秒，或显式 unload
    v
[stopped]  worker 退出；显存释放
```

重新加载由“worker 是否仍然存活”决定，而不是由模型累计运行时间决定：

| 情况 | 下次分割是否重新加载 |
| --- | --- |
| MCP Server 启动后的第一次分割 | 是 |
| 上次请求完成后 120 秒内再次分割 | 否，复用同一 PID |
| 空闲超过 120 秒后再次分割 | 是 |
| 只调用 `get_sam3_status` | 不加载，也不续期 |
| 调用 `unload_sam3` 后再次分割 | 是 |
| MCP Server 重启 | 是 |
| worker 异常退出、OOM 或协议损坏 | 是 |
| 加载或推理超过 request timeout | 是 |
| 普通无效输入且 worker 仍健康 | 通常不需要 |

时序示例：

```text
12:00:00  第一次推理完成，开始 120 秒计时
12:01:20  第二次推理开始，取消旧计时，不重新加载
12:01:21  第二次推理完成，从此刻重新计时
12:03:21  连续空闲满 120 秒，worker 退出
12:05:00  第三次请求到来，重新加载模型
```

推理执行时间不计入空闲时间；空闲计时从请求完成、状态重新变成 `ready` 时开始。

### 9.7 并发、取消和卸载

当前 manager 使用两类异步锁：

- 请求锁保证同一个 worker 同时只执行一个推理请求；并发分割请求会排队串行处理。
- 状态锁只保护 PID、状态和计时器等短时状态，因此 `get_sam3_status` 和 `unload_sam3` 不会被整段推理长期阻塞。

生命周期规则：

- 状态查询在推理期间返回 `busy` 和当前 request ID。
- 显式 unload 可以中断正在运行的推理，并把状态收敛到 `stopped`。
- Agent 取消调用时，manager 会先完成 worker 清理，再把取消继续向上传播。
- timeout、管道错误、无效成功结果或协议超限都会丢弃 worker，避免留下一个看似 `busy`、实际不可用的进程。
- 单 worker 不做 GPU 并行推理，优先保证 8 GB 显卡上的可预测显存占用。

### 9.8 已经有 MCP，为什么还需要 worker

MCP 与 SAM3 worker 解决的是不同层次的问题：

| 组件 | 主要职责 | 不负责什么 |
| --- | --- | --- |
| MCP Tool | 向 LLM 暴露稳定工具名、参数、描述和结构化返回值 | 不应直接承担重型模型生命周期 |
| Process Manager | 把一次 Tool 调用转换成可控的进程请求 | 不实现神经网络推理 |
| SAM3 worker | 加载模型、占用 GPU、执行推理和写入 artifacts | 不直接面向 LLM 或负责工具发现 |

如果直接在 MCP Server 进程中 import 并加载 SAM3：

- SAM3 的 PyTorch/CUDA 依赖会污染主 MCP Python 环境。
- 模型 OOM、崩溃或退出可能直接拖垮全部 MCP 工具。
- 难以在不重启 MCP Server 的情况下真正释放 CUDA context 和显存。
- 无法清晰区分“工具协议仍可用”和“GPU 模型暂时不可用”。

子 worker 让 MCP Server 保持轻量和稳定，同时允许模型按需启动、独立退出和彻底释放显存。它不是另一套 MCP，也不与 MCP 重复。

### 9.9 当前 worker 的共享范围

当前 worker 不是机器级全局服务，而是隶属于一个 MCP Server 进程：

- 同一 MCP Server 的请求复用同一个 worker。
- 不同 MCP Server 不共享 worker。
- 多个 stdio MCP Server 可能分别加载一份模型。
- 在 8 GB GPU 上，多份 SAM3 很可能 OOM。

当前单 Agent、单 MCP Server 场景适合继续使用子 worker。若未来多个 Agent、机器人或设备需要共享同一块 GPU，应升级为机器级单例服务：

```text
多个 Agent / 机器人
    |
一个或多个 MCP Server
    |
HTTP / gRPC / Unix socket
    |
机器级 SAM3 服务
    |
单份 GPU 模型 + 统一请求队列
```

升级后，MCP 仍负责 Tool 契约；独立服务负责模型、并发、批处理、限流和 GPU 调度。

### 9.10 环境配置

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `ROBOCLAW_SAM3_PYTHON` | MCP Python | 隔离 SAM3 Python 路径 |
| `ROBOCLAW_SAM3_SOURCE` | 必填 | 外部 SAM3 checkout |
| `ROBOCLAW_SAM3_CHECKPOINT` | 必填 | 外部 `sam3.pt` |
| `ROBOCLAW_SAM3_CHECKPOINT_SHA256` | 确认 digest | 验证并记录 checkpoint 身份 |
| `ROBOCLAW_SAM3_DEVICE` | `cuda` | `cuda` 或 `cpu` |
| `ROBOCLAW_SAM3_INPUT_ROOTS` | 仓库根目录 | 允许读取的图片根目录 |
| `ROBOCLAW_SAM3_OUTPUT_ROOT` | `runtime_data/sam3` | 结果根目录 |
| `ROBOCLAW_SAM3_IDLE_TIMEOUT_SEC` | `120` | 推理完成后的空闲回收时间 |
| `ROBOCLAW_SAM3_REQUEST_TIMEOUT_SEC` | `120` | 启动或单次推理的最大时间 |

```bash
export ROBOCLAW_SAM3_PYTHON=/opt/conda/envs/sam3/bin/python
export ROBOCLAW_SAM3_SOURCE=/opt/sam3
export ROBOCLAW_SAM3_CHECKPOINT=/models/sam3.pt
export ROBOCLAW_SAM3_INPUT_ROOTS=/data/robot_images
export ROBOCLAW_SAM3_OUTPUT_ROOT=/var/lib/roboclaw/sam3-results
export ROBOCLAW_SAM3_IDLE_TIMEOUT_SEC=120
export ROBOCLAW_SAM3_REQUEST_TIMEOUT_SEC=180
```

`IDLE_TIMEOUT` 控制请求结束后模型保留多久；`REQUEST_TIMEOUT` 控制一次加载或推理最多执行多久。`REQUEST_TIMEOUT=180` 不代表模型驻留 180 秒。

两个 timeout 都必须是大于 0 的有限数值。当前没有“永不回收”的特殊值；如果希望更长时间驻留，应设置一个明确的较大 `IDLE_TIMEOUT`。

### 9.11 源码和 checkpoint 完整性

固定官方源码 revision：

```text
6dbb02bd38288df755dfa1378000a861e65b84f6
```

确认 checkpoint：

```text
Size:    3450062241 bytes
SHA-256: 9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e
```

worker 加载模型前会：

1. 检查外部路径是否存在。
2. 校验 Git HEAD 是否等于固定 revision。
3. 通过 `git status --porcelain --untracked-files=all` 确认 checkout 干净。
4. 校验 checkpoint 文件大小。
5. 读取整个 checkpoint 并计算 SHA-256。
6. 只有全部通过后才加载官方模型。

RoboClaw 只调用官方推理入口 `build_sam3_image_model` 和 `Sam3Processor`，不包含或调用训练、数据集与训练配置代码。

### 9.12 输出 artifacts

每个成功请求使用独立 request ID：

```text
runtime_data/sam3/<request-id>/
  result.json
  masks.npz
  mask_000.png
  mask_001.png
  overlay.png
```

写入过程先使用同级隐藏临时目录，全部文件完成后再原子重命名为最终目录，避免调用方看到半成品。

| artifact | 内容 |
| --- | --- |
| `result.json` | 输入身份、prompt、score、box、mask 面积、模型版本和耗时 |
| `masks.npz` | 名为 `masks` 的 bool 数组，形状为 `(N, H, W)` |
| `mask_NNN.png` | 每个实例的单通道 0/255 mask |
| `overlay.png` | 在原图上叠加 mask 的预览图 |

MCP 返回 `instance_count`、每个实例的 `score`、像素 `xyxy` box、mask 面积、worker PID、加载/推理耗时及上述文件路径。

无检测时仍会生成：

- `instance_count=0`。
- 形状为 `(0, H, W)` 的空 `masks` 数组。
- 保留原图内容的 overlay。
- 完整的 `result.json`。

### 9.13 错误和 worker 协议

SAM3 Runtime 错误转换为结构化 `ok=false`，不会关闭 MCP transport。

| 错误码 | 含义 | worker 行为 |
| --- | --- | --- |
| `INVALID_INPUT` | 路径、图片、prompt、threshold 或输出无效 | 通常保留 |
| `MODEL_UNAVAILABLE` | 环境、依赖、模型或 CUDA 不可用 | 停止 |
| `SOURCE_REVISION_MISMATCH` | 源码 revision 不匹配或 checkout 不干净 | 启动失败 |
| `CHECKPOINT_MISMATCH` | checkpoint 大小或实测 SHA-256 不匹配 | 启动失败 |
| `GPU_OOM` | CUDA 显存分配失败 | 停止 |
| `INFERENCE_TIMEOUT` | 加载或推理超时 | 停止 |
| `WORKER_EXITED` | worker 退出、返回无效结果或协议异常 | 停止并丢弃 |
| `OUTPUT_EXISTS` | request ID 的最终目录已经存在 | 保留 |
| `OUTPUT_WRITE_FAILED` | artifacts 无法原子写入 | 通常保留 |

worker stdout 只能输出 JSON Lines 协议消息，操作日志和第三方警告写入 stderr。manager 会清理控制字符、限制单条日志长度并转发到操作日志。

单条 stdout 协议消息上限为 4 MiB。消息超限、无法读取、JSON 损坏、request ID 不匹配或成功结果结构不合法时，manager 会返回 `WORKER_EXITED` 并停止 worker，不让状态滞留在 `busy`。

### 9.14 RTX 4060 验收数据

在 8188 MiB RTX 4060 上，使用 1800×1200 图片、prompt `truck`、threshold `0.3` 的结果：

| 指标 | 结果 |
| --- | --- |
| 首次加载 | 约 7.4 秒 |
| 第一次推理 | 约 0.52–0.56 秒 |
| 第二次推理 | 约 0.32–0.36 秒 |
| 连续两次请求 | PID 相同，证明模型复用 |
| GPU 基线 | 约 571 MiB |
| GPU 总峰值 | 约 6043 MiB |
| SAM3 增量 | 约 5472 MiB |
| 显式或空闲卸载后 | 回到约 571 MiB，worker PID 消失 |

这些数据用于证明当前生命周期设计能够加载、复用和卸载模型，不是所有输入、prompt 和 GPU 上的固定性能保证。

### 9.15 当前方案的使用建议

| 场景 | 建议 |
| --- | --- |
| 单 Agent、偶尔连续调用 SAM3 | 保持当前默认 120 秒懒加载 worker |
| 连续处理多张图片 | 在空闲窗口内发送请求，避免重复加载 |
| GPU 还要运行其他大模型 | 推理结束后主动调用 `unload_sam3` |
| 首次探索目标 | threshold 从 `0.5` 开始，漏检时降到 `0.3` |
| 只接受高可信目标 | threshold 提高到 `0.6–0.8` |
| 多 Agent 共享同一 GPU | 不要启动多个本地 worker；升级为机器级 SAM3 服务 |
| 需要直接消费 ROS Image Topic | 增加 ROS 图像落盘/桥接 Tool，再调用当前图片分割 Tool |

## 10. 如何使用工具

### 10.1 让 LLM 自动调用

示例客户端：`roboclaw_next/examples/RuboclawClient.py`。

它会：

1. 启动 `python -m roboclaw_next.tools.mcp_server`。
2. 建立 MCP Session。
3. 调用 `list_tools()`。
4. 将 MCP tools 包装并注册为 Agent tools。
5. 把工具 Schema 与消息发给 LLM。
6. 执行 LLM 返回的 tool calls。
7. 将结果回填给 LLM，直到得到最终回答。

自然语言示例：

```text
启动模拟定位，读取当前位置，然后规划到 x=5、y=3、yaw=0 的路径。
```

```text
确认定位和最新路径正常后，启动 MPC 跟踪。
```

```text
计算右臂当前末端位姿，并规划到 arm_origin 中
x=0.35、y=-0.15、z=0.30 的轨迹，不要执行电机。
```

```text
用 SAM3 分割 /data/robot_images/frame.png 中的 red cup，置信度 0.5。
```

### 10.2 直接调用 MCP

```python
import asyncio
import os
import sys

from roboclaw_next.tools import MCPClientRuntime, StdioMCPServerConfig


async def main() -> None:
    config = StdioMCPServerConfig(
        name="roboclaw_tools",
        command=sys.executable,
        args=["-m", "roboclaw_next.tools.mcp_server"],
        env=os.environ.copy(),
    )

    async with MCPClientRuntime(config) as runtime:
        tools = await runtime.list_tools()
        print([tool.name for tool in tools])

        status = await runtime.call_tool("get_sam3_status", {})
        print(status.structuredContent)

        result = await runtime.call_tool(
            "segment_image_with_sam3",
            {
                "image_path": "/data/robot_images/frame.png",
                "text_prompt": "red cup",
                "confidence_threshold": 0.5,
            },
        )
        print(result.structuredContent)

        await runtime.call_tool("unload_sam3", {})


asyncio.run(main())
```

直接 MCP 调用使用原始工具名，不使用 `roboclaw_tools__` 前缀。

### 10.3 SAM3 CLI

不经过 MCP 执行一次推理：

```bash
python -m robot_runtime.perception.sam3 infer \
  --image /data/robot_images/frame.png \
  --prompt "red cup" \
  --confidence 0.5
```

手动启动 JSON Lines worker：

```bash
python -m robot_runtime.perception.sam3 serve
```

worker stdout 只能输出协议 JSON；调试和操作日志必须写入 stderr。管理器将单条协议消息限制为 4 MiB；消息超限或管道读取失败时会停止并丢弃 worker，以结构化的 `WORKER_EXITED` 返回，而不会让状态滞留在 `BUSY`。

## 11. 新增机器人或场景工具

### 11.1 先选择运行模式

| 问题 | 推荐模式 |
| --- | --- |
| 计算快、依赖一致、无长期状态 | 进程内纯函数 |
| 每个操作独立并自然退出 | 单次 subprocess runner |
| ROS 节点持续发布、订阅或控制 | `start/status/stop` manager |
| 模型加载昂贵，需要复用和回收 GPU | lazy worker |
| 多个 MCP Server 必须共享同一资源 | 机器级独立服务 |

### 11.2 目录结构

```text
roboclaw_next/tools/builtin/<tool_name>/
  __init__.py
  tool.py
  program.py
  tests/

robot_runtime/<domain>/<implementation>/
  __init__.py
  ...
  tests/
```

### 11.3 `program.py` 原则

- 提供不依赖 MCP 的 Python API。
- 管理重复 start/stop/unload。
- 保存 PID、退出码和状态。
- 处理 timeout、terminate、kill 和异步取消。
- 分离 stdout 机器协议和 stderr 日志。
- 验证输入路径和允许目录。
- 返回结构化、稳定、可恢复的错误。

### 11.4 `tool.py` 原则

- 参数名清晰，写出单位和 frame。
- 数值拒绝 NaN/Infinity。
- 结果结构化，不依赖解析自然语言。
- 大文件和数组返回路径，不直接进入 LLM context。
- 描述写清前置条件与能力边界。
- 状态查询不得隐式加载昂贵资源。
- 停止和卸载尽量幂等。
- 规划和执行分成不同工具。

### 11.5 注册

```python
from .builtin.example.program import ExampleProcessManager
from .builtin.example.tool import register_example_tools

example_manager = ExampleProcessManager()
register_example_tools(mcp, example_manager)
```

多个工具依赖同一机器人状态时，必须共享 manager，不要创建互不知情的重复管理器。

### 11.6 场景物体如何封装

场景物体不一定要直接变成独立 MCP Server。推荐先区分：

```text
物体数据
  ID、类别、位姿、尺寸、置信度、坐标系、时间戳

物体能力
  查询、检测、分割、抓取位姿估计、移动、状态更新
```

Tool 应表达动作，例如：

```text
list_scene_objects
get_scene_object_pose
segment_scene_object
estimate_grasp_pose
move_object
```

而不是为每个杯子、箱子或桌子创建一个新的 Server。物体作为结构化参数和返回值，能力作为 Tool。涉及真实运动或修改环境的工具必须明确坐标系、安全边界和 destructive annotations。

## 12. 测试与验收

MCP 和 builtin 工具：

```bash
python -m unittest discover -s roboclaw_next -t . -p 'test_*.py' -v
```

SAM3 runtime：

```bash
python -m unittest discover -s robot_runtime -t . -p 'test_*.py' -v
```

某些未包含 `__init__.py` 的测试目录需要单独发现：

```bash
python -m unittest discover \
  -s roboclaw_next/tools/builtin/path_tracking/tests \
  -p 'test_*.py' -v

python -m unittest discover \
  -s robot_runtime/control/differential_drive_mpc/tests \
  -p 'test_*.py' -v
```

SAM3 CPU-only 测试使用 fake backend，不导入 torch，不需要 GPU。真实部署验收还需要：

1. 校验源码 revision、checkpoint 大小和 SHA-256。
2. 第一次真实 GPU 推理成功。
3. 第二次请求复用同一 PID。
4. 峰值显存不超过部署预算。
5. `unload_sam3` 后显存回落。
6. 空闲超时后状态变为 `stopped` 且显存回落。
7. 回收后的下一次请求重新加载并成功。

## 13. 常见问题

### LLM 看不到工具

检查工具是否在 `mcp_server.py` 注册、MCP Server 是否启动、Client 是否执行 `initialize()`/`list_tools()`，以及 adapter 是否已加入 `ToolRegistry`。

### 定位 running 但读不到 pose

检查 ROS 2 Humble、`install/setup.bash`、`roboclaw_interfaces` 和 `/mock_localization/get_pose` 服务。

### Hybrid A* 找不到 executable

检查 ROS install 目录或 standalone build 目录，并确认 Linux 执行权限。

### MPC 无法启动

依次检查定位状态、路径文件是否存在、规划 `success`、waypoint 结构和 MCP Server 的 ROS 环境。

### SAM3 每次都重新加载

检查：

- 是否每次都新建 MCP stdio Server。
- 两次调用间隔是否超过 idle timeout。
- 是否调用了 `unload_sam3`。
- 上次是否发生 OOM、timeout 或 worker exit。
- 两次结果的 `worker_pid` 是否一致。

### SAM3 长时间占用显存

查看 `get_sam3_status` 的 `state`、`pid`、`last_activity_at` 和 `idle_timeout_sec`。需要立即释放时调用 `unload_sam3`；需要更快回收时降低 idle timeout，但过短会导致频繁承担约数秒加载成本。

### SAM3 在 8 GB GPU 上 OOM

检查是否存在多个 MCP Server/worker、其他 GPU 任务、threshold 是否为 `0.0`、图片是否过大以及 PyTorch/CUDA 环境是否正确。OOM 后 manager 会停止 worker；清理 GPU 负载后，下次请求重新加载。

## 14. 相关入口

| 内容 | 路径 |
| --- | --- |
| 工具概览 | `roboclaw_next/tools/README.md` |
| LLM 工具调用流程 | `roboclaw_next/docs/howtoolsareusedbyllm.md` |
| Agent/MCP 示例 | `roboclaw_next/examples/RuboclawClient.py` |
| MCP 注册入口 | `roboclaw_next/tools/mcp_server.py` |
| SAM3 运行说明 | `robot_runtime/perception/sam3/README.md` |
| SAM3 配置 | `robot_runtime/perception/sam3/config.py` |
| SAM3 官方 backend | `robot_runtime/perception/sam3/backend.py` |
| SAM3 worker 协议 | `robot_runtime/perception/sam3/worker.py` |
| SAM3 输入与 artifacts | `robot_runtime/perception/sam3/engine.py` |

## 15. 当前能力边界

- 模拟定位不是真实 SLAM/定位系统。
- Hybrid A* 使用当前固定 PNG 地图。
- MPC 依赖已有定位和路径。
- OpenArm 只计算 FK/IK，不执行电机命令。
- SAM3 只处理本地单张图片，不直接消费 ROS Image Topic 或视频。
- SAM3 worker 只在一个 MCP Server 内复用，不是全局共享服务。

后续接入真实机器人、场景物体、ROS Topic 或机器级推理服务时，应继续保持“稳定 MCP 契约”和“可替换 `robot_runtime` 实现”的边界。
