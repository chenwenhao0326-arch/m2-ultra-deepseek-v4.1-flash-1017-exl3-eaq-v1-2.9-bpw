# 测速方法与解释

发布的历史记录在`benchmarks/m2-ultra-224-288-20261026.json`，保留了精确提示词、生成文本、token数量、TTFT、引擎生成速度、总耗时、采样参数、缓存保留和二进制标识。

## 比较范围

**A 已经包含 M2 运行适配和此前积累的优化；B 在 A 上增加新上游方案的选择性缓存适配。A 不是上游未经修改的版本。** 两版都使用 M2 适配库，且保留输入处理、算子、回答检查点、RAM／SSD 状态和已有专家记录复用等相同功能。

本轮约5.9%的总耗时改善只归属于这次增量比较。它不表示整个项目仅有这一项工作，也不能作为全部适配与优化相对原作者方案的累计收益。三层工作的代码对应关系见[适配说明](ADAPTATIONS.md)。

顺序为现场A基线，然后B优化版。每个进程使用独立SSD会话缓存命名空间，固定预热，再进行中文技术说明、代码和依赖上一条代码的追问。原实验每个进程启动前空闲20秒。首字时间与生成时间分开报告；三项总耗时不包含进程加载和预热，这两者也不算TPS收益。

## 自己重测

每次比较都重新跑A，不使用这份历史分数作为新基线。两版使用相同模型目录和参数，等待其他GPU任务空闲。

```bash
python3 scripts/service.py start --profile baseline --model "$MODEL_DIR"
# 等待 ready
python3 scripts/benchmark.py --arm A --output results/A-new.json
python3 scripts/service.py stop

python3 scripts/service.py start --profile optimized --model "$MODEL_DIR"
# 等待 ready
python3 scripts/benchmark.py --arm B --output results/B-new.json --compare results/A-new.json
```

脚本默认关闭思考，temperature1、top_p0.95，主问题seed42，上限1024；追问seed43，上限512。预热为1到30的计数，seed123、上限80。A/B的请求或配置不同则拒绝归因；原始回答和失败都会保存，不能按回答正确与否挑选重试。

同时检查服务日志中的实际保留量、回收等待、磁盘读取与外部负载。按需专家读取计数不是SSD物理NAND流量。内存取进程footprint、resident、wired中最大的值，不把互相重叠的指标相加。

## 已观察的边界

- 此档只有一组完整A/B；此前245／310档的两组结果支持同一方法，但不能当成同档重复样本。
- 全部三条已测输入输出相同，不是完整能力评测，也不证明所有采样序列永远一致。
- 约157GiB峰值和零swap只描述这些测试。
- 新保留策略的合格范围是<=256个未缓存输入tokens或验证过的短后缀。DSH的长系统提示可能走原路径。
- 回收统计等待可能增加TTFT；表格同时给出这一成本。
- 未声称稳定35–40tok/s，未把作者M5／STQ的成绩移作M2／EXL3保证。

未获得稳定整模型净收益的延迟核验、部分算子融合、扩大分组、Down系数改写等保持关闭。新统计接口与宽输入试验未进入本次发布补丁。
