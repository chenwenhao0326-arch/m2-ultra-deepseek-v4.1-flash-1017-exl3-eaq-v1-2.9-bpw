# M2 Ultra + DeepSeek Flash-1017 EXL3 EAQ v1

This is an independent deployment experiment for an Apple M2 Ultra with 192 GiB unified memory. The model is by DeepSeek-AI, the EXL3 EAQ v1 quantization by Mia-AiLab, and the streaming repack by OpensourceWTF. The runtime is based on pinned mlx-serve and mlx-stream sources, with attributed Sushi-inspired adaptations. See [NOTICE](../NOTICE).

The qualified profile uses 224 prefill cache slots and 288 decode cache slots per layer, a configured 262,144-token context, all routed experts, and the existing DSpark sampling/acceptance behavior. Missing expert records are streamed from SSD. The package does not contain weights or download them automatically.

The new change retains inactive extension-cache owners between requests and releases only as many late-layer owners as the actual native/process/host budgets require. It preserves the base pool, original math and memory checks. The qualified scope is up to 256 uncached input tokens or a native-verified short suffix over a longer prefix; larger uncached inputs fall back to the previous path.

One fresh same-profile A/B suite measured 21.769→22.873 tok/s for text, 29.628→31.465 for code, and28.429→32.982 for a code follow-up. All request payloads and outputs matched. Total measured task time was 104.152→98.017 seconds; sampled process peaks were 157.161/157.139 GiB, with no added swap. TTFT costs are also reported. These are local observations, not a universal 35–40 tok/s claim or a filled 256K-context stress test.

Read [build instructions](BUILD.md), [operations/rollback](OPERATIONS.md), and [benchmark methodology](BENCHMARKS.md). Code-only package checks run with:

```bash
python3 -m unittest discover -s tests -v
```

The initial publication reconstructs the exact changed source files and builds with cached compatible native dependencies. A second-machine clean dependency build and full-model rerun of the relocated package are not claimed. Public scripts use separate ports 18000/18002 and a local ignored runtime directory.
