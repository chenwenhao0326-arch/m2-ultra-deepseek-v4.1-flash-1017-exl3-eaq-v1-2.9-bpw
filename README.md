# M2 Ultra + DeepSeek-V4.1-Flash-1017 EXL3 EAQ v1 2.9 bpw

在 **M2 Ultra、192 GiB 统一内存**上运行 DeepSeek 的独立部署与优化实验项目。基于 [mlx-serve](https://github.com/ddalcu/mlx-serve) 和 [mlx-stream](https://github.com/davidtai/mlx-stream)，部分缓存与算子实现参考 [Sushi](https://github.com/beamivalice/sushi)。

**模型由 DeepSeek-AI 提供，量化由 Mia-AiLab 提供，流式重打包由 OpensourceWTF 提供。** 本仓库维护本地工程适配、运行脚本和实测记录，具体署名及许可见 [NOTICE](NOTICE)。

An independent, reproducible M2 Ultra deployment experiment. Pinned source patches, a source-checked M2 adapter, guarded localhost service scripts, and transparent same-configuration A/B measurements. See [English overview](docs/README.en.md).

## 当前版本

| 项目 | 设置 |
| --- | --- |
| 硬件 | M2 Ultra，76 核 GPU，192 GiB 统一内存 |
| 实测系统 | macOS 26.4.1；构建最低目标 26.2 |
| 模型 | DeepSeek-V4.1-Flash-1017，EXL3 EAQ v1 2.9 bpw |
| 输入／生成专家缓存 | 每层 224／288 个槽位 |
| 配置上下文 | 262,144 tokens（256K） |
| 专家 | 全部保留；缓存缺失时从 SSD 读取 |
| DSpark | 保留原有策略与接受规则 |
| 服务范围 | 文字与工具协议；默认仅监听 127.0.0.1 |

224／288 是缓存容量，不是模型的激活专家数。模型仍有每层 384 个路由专家。35 层使用 K3，18–22 层使用 K2；路由专家的 EXL3 权重没有再次量化。

## 本轮改动与实测

生成转回输入阶段时，按实际内存预算释放必要的后部扩展缓存，保留其余专家记录，供后续生成复用。保留完整原生预算、同步与回收校验；没有改变权重、采样或投机接受规则。

下表来自**同一台机器、同一缓存档位，重新测 A 基线后测 B 优化版**。temperature=1、top_p=0.95、seed=42、关闭思考；固定预热，输入与输出逐字一致。

| 场景 | A 基线 | B 优化 | 生成速度变化 |
| --- | ---: | ---: | ---: |
| 中文技术说明，生成 1024 tokens | 21.769 tok/s | 22.873 tok/s | +5.1% |
| Python 代码，生成 912 tokens | 29.628 tok/s | 31.465 tok/s | +6.2% |
| 带历史的代码追问，生成 512 tokens | 28.429 tok/s | 32.982 tok/s | +16.0% |
| 三次请求总耗时（不含加载、预热） | 104.152 秒 | 98.017 秒 | −5.9% |
| 进程采样峰值 | 157.161 GiB | 157.139 GiB | 基本不变 |
| 新增 swap | 0 | 0 | — |

完整提示词、回答、计时、源码／程序标识与限制见 [实测 JSON](benchmarks/m2-ultra-224-288-20261026.json) 和 [测速说明](docs/BENCHMARKS.md)。首字时间没有隐去：文字 2.699→3.010 秒，代码 2.669→2.661 秒，追问 2.472→2.546 秒。

**这是一组当前档位的实测，不是所有任务都能达到 35–40 tok/s 的保证。** 256K 是配置和预算范围，这组测速没有填满 256K 输入。

## 构建与使用

需要 Python 3.9+、Git、Node.js 18+、Zig 0.17.0，以及兼容的 Xcode/Metal 工具链。先阅读 [构建说明](docs/BUILD.md)；这是源码实验版，不提供自动修改系统内存额度的安装器。

```bash
git clone https://github.com/chenwenhao0326-arch/m2-ultra-deepseek-v4.1-flash-1017-exl3-eaq-v1-2.9-bpw.git
cd m2-ultra-deepseek-v4.1-flash-1017-exl3-eaq-v1-2.9-bpw

# 显式获取固定版本的代码与依赖；不下载模型
python3 scripts/prepare.py --profile optimized --download
python3 scripts/setup_deps.py --profile optimized --allow-downloads
python3 scripts/build.py --profile optimized

# MODEL_DIR 指向另行取得的完整流式模型包
python3 scripts/service.py doctor --model "$MODEL_DIR"
python3 scripts/service.py start --profile optimized --model "$MODEL_DIR"
python3 scripts/service.py status
```

页面：`http://127.0.0.1:18000/`；OpenAI 兼容 API：`http://127.0.0.1:18000/v1/`。默认使用独立端口和 `.local/` 运行目录，日志也保存在其中。停止命令：

```bash
python3 scripts/service.py stop
```

模型包使用 [OpensourceWTF 的流式重打包](https://huggingface.co/OpensourceWTF/DeepSeek-V4.1-Flash-1017-streaming-repack-exl3-2.9bpw)，修订 `3ef807df042b7069ccefc0957b6df5ff5fa9267f`，总计约 417.83 GB。它来源于 [Mia-AiLab 的 EXL3 EAQ v1 量化](https://huggingface.co/Mia-AiLab/DeepSeek-V4.1-Flash-1017-EXL3-EAQ-v1-2.9-bpw)。本仓库不包含模型权重，启动脚本也不会自动下载权重。

## 边界与回滚

- 当前新增保留策略适用于不超过 256 个未缓存输入 tokens，或已由引擎验证的长历史短后缀。较大新增输入仍走原流程。
- 保留量取决于实际内存余量；等待 macOS 回收统计可能增加首字延迟。
- 已验证配置为文字服务。多模态和未获得稳定整模型收益的试验保持关闭。
- 进程保护 180 GiB、整机保护 190 GiB；记录内存压力与 swap。测试机器的 GPU 额度设置另见 [运行说明](docs/OPERATIONS.md)。
- 可构建 `baseline`，在相同 224／288／256K 配置下回滚或重测；命令见 [运行说明](docs/OPERATIONS.md)。

## 仓库内容

- `patches/`：固定上游版本之上的基础适配与独立缓存改动。
- `m2/`：与实测适配库对应的 C/Metal 源码。
- `config/`：运行参数、模型头指纹、相同初始化用的专家统计。
- `scripts/`：准备、构建、启动、停止和测速。
- `benchmarks/`：经过清理的实测条件与结果。
- `licenses/`：上游及第三方许可与署名。

欢迎提供包含硬件、版本、参数和原始计时的复现报告；后续更新以可复现的证据为依据。
