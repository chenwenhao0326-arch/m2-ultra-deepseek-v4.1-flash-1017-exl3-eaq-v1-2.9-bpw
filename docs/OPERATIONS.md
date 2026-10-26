# 启动、停止和回滚

固定配置为224个输入缓存槽、288个生成缓存槽和256K上下文。启动前先完成构建并准备完整的固定修订模型包。

```bash
export MODEL_DIR=/path/to/DeepSeek-V4.1-Flash-1017-EXL3-2.9bpw
python3 scripts/service.py doctor --model "$MODEL_DIR"
python3 scripts/service.py start --model "$MODEL_DIR" --profile optimized
python3 scripts/service.py status
```

等待状态为`ready`后访问`http://127.0.0.1:18000/`。代理保留流式事件，并使用已修正的前端空闲超时处理；原生后端使用18002。可通过`--port`和`--backend-port`换端口，两者必须空闲且不同。服务只监听127.0.0.1。

其他支持自定义OpenAI兼容地址的客户端可连接`http://127.0.0.1:18000/v1/`。通过`/v1/models`读取实际模型ID。DSH属于独立客户端，不包含在这个仓库里。

## 内存环境

实测机器：192GiB物理内存，`iogpu.wired_limit_mb=194560`（190GiB额度）。这是允许的GPU工作集上限，不是预占190GiB。普通系统默认额度未必满足相同的原生预算。

脚本读取并检查现有额度，不自动写入sysctl或启动项；额度低于180GiB时该实验档位拒绝启动。是否调整全局额度由机器所有者决定，应同时考虑其他应用。应用仍执行原生分配前检查，以及180GiB进程、190GiB整机、内存压力和swap增长监控。只结束本工具创建的进程，不处理其他项目。

157GiB是短输入任务的采样峰值，不是所有上下文下的承诺。256K是配置范围；随着输入、缓存保留及其他应用变化，内存和首字时间会改变。默认空闲300秒后由引擎释放模型。

## 日志与缓存

- `.local/service.json`：配置、进程身份和当前状态。
- `.local/logs/<时间>/server.log`：引擎输出。
- 同目录`memory.jsonl`：每秒的内存、swap和保护原因。
- `.local/native-cache/`：原生会话状态；基线与优化版使用独立身份。
- `.local/`与`results/`均被Git忽略；其中可能包含本机路径或聊天内容。

## 停止与回滚

```bash
python3 scripts/service.py stop
python3 scripts/service.py start --model "$MODEL_DIR" --profile baseline
```

先构建基线。回滚使用相同224／288／256K和采样设置，只切换缓存改动。停止前请等待当前回答结束；本工具的`stop`是明确的停止操作，会终止它管理的服务。`status`使用进程启动时间与命令核对身份，避免对复用的PID操作。
