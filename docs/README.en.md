# M2 Ultra + DeepSeek Flash-1017 EXL3 EAQ v1

This is an independent inference adaptation and optimization project for an Apple M2 Ultra with 192 GiB unified memory. It reuses DeepSeek-AI's model, Mia-AiLab's EXL3 EAQ v1 quantization, and OpensourceWTF's streaming repack. The host and plugin are based on pinned mlx-serve and mlx-stream sources. See [NOTICE](../NOTICE).

At the upstream revisions and M2 environment tested in this project, the complete serving path required kernel and runtime adaptation. The quantized expert weights could be reused, but downloading them and using the original serving path unchanged was not sufficient. This is a statement about the pinned setup, not every later upstream revision or every Apple Silicon machine.

## Three layers of work

### 1. Enable the runtime on M2

Adapt matrix-kernel paths that depend on NAX to M2-compatible SIMD execution, while preserving the corresponding EXL3 codebook and numerical rules. Migrate the earlier M2 work to the 1017 pack's mixed K2/K3 geometry, check record layouts and scratch accounting, and integrate host/plugin contracts, templates, text/tool protocols and state lifecycles.

The supplied quantized expert weights are not retrained or requantized. The M2 adapter and core patches are essential parts of the working setup.

### 2. Retain established local optimizations

The existing baseline already includes cache-hit-first prefill scheduling and cross-batch handling, qualified M2 Gate/Up reuse, complete-answer checkpoints, RAM/SSD native session-state reuse, verified long-prefix handling, and expert-record reuse. Serving compatibility, stream timeout handling, logging and rollback are also included, but are not counted as generation-TPS improvements.

These changes include adaptations of existing project implementations as well as local engineering and validation. They predate the latest selective-retention work.

### 3. Adapt selected new upstream PR/commit ideas

The latest included increment follows Sushi's cache-borrowing approach, pinned to [b68302a](https://github.com/beamivalice/sushi/blob/b68302a1469ed7d2dab03530cc10c6e2685f2a0a/src/dsv41_borrow.zig). The local EXL3 implementation releases only the necessary inactive extension-cache owners, retains the base pool, and rechecks actual memory after synchronization and reclamation. It accounts for mixed K2/K3 owners and delayed macOS statistics.

It does not import the author's STQ weights or assume their hardware results apply to M2. Only the qualified short-input/verified-short-suffix path is enabled; larger uncached inputs keep the previous fallback.

The [adaptation map](ADAPTATIONS.md) links these layers to the published files. The patch layout is functional: the host patch, baseline plugin patch and M2 adapter contain the first two layers; the separate selective-cache patch adds the third.

## What the A/B numbers measure

**A is our already-adapted, already-optimized local baseline. B is A plus the third-layer selective cache adaptation. A is not unmodified upstream.**

With the same 224/288 cache slots, configured 262,144-token context, original DSpark behavior and sampling settings, one fresh A/B suite measured:

| Case | A: existing adapted baseline | B: additional selective retention |
| --- | ---: | ---: |
| Text | 21.769 tok/s | 22.873 tok/s |
| Code | 29.628 tok/s | 31.465 tok/s |
| Code follow-up | 28.429 tok/s | 32.982 tok/s |

All measured request payloads and outputs matched. Total task time was 104.152 → 98.017 seconds, and sampled process peaks were 157.161 / 157.139 GiB with no added swap. TTFT costs are also recorded.

The 5.9% task-time reduction is the incremental third-layer result, not a cumulative speedup for the entire project. Historical changes involve different stages, versions and workloads; their percentages cannot simply be added. These observations do not establish universal 35–40 tok/s or a filled-256K-context stress result.

## Build and validation

Read [build instructions](BUILD.md), [operations/rollback](OPERATIONS.md), and [benchmark methodology](BENCHMARKS.md). Both build profiles retain the first two layers. Code-only package checks run with:

```bash
python3 -m unittest discover -s tests -v
```

The publication reconstructs the exact changed source files and builds with cached compatible native dependencies. A second-machine clean dependency build and a full-model rerun of the relocated package are not claimed. Public scripts use separate ports 18000/18002 and an ignored local runtime directory. Model weights are obtained separately.
