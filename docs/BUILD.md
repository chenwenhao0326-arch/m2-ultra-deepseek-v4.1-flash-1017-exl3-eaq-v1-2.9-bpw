# 构建与固定版本

这份实验包使用补丁而不是复制整个上游仓库。`sources.lock.json` 固定上游 commit、已有归档哈希、每个改动文件的前后指纹及 M2 适配源码哈希。准备阶段先校验原文件，再应用补丁并核对结果。

## 环境

- Apple Silicon macOS 26.2+，本项目只在 M2 Ultra 192 GiB 上验证。
- Xcode 26.2+ 及 Metal Toolchain；`xcrun -sdk macosx metal --version` 应可用。
- Python 3.9+、Git、Zig **0.17.0**、CMake、libwebp 1.6+、Node.js 18+（可通过 PATH 或 `NODE_BINARY` 指定）。
- Homebrew 用户可自行安装依赖：`brew install cmake libwebp node`。
- 模型约 418 GB；另预留代码、工具链、编译目录和本地状态缓存空间。

## 在线准备

```bash
python3 scripts/prepare.py --profile optimized --download
python3 scripts/setup_deps.py --profile optimized --allow-downloads
python3 scripts/build.py --profile optimized
```

`prepare` 获取 `ddalcu/mlx-serve@94670d9…` 与 `davidtai/mlx-stream@fcb4011…`，并检查上游子模块。依赖阶段调用该固定版本的工具链和原生库构建脚本，可能下载较多代码及原生库，使用本机 Git/curl 的网络设置。模型下载不属于这些步骤。

Zig 默认从准备后的 `host/.zig-toolchain/zig` 查找，也可指定 `--zig /path/to/zig`。非 Homebrew 的 webp 可通过 `--webp-prefix /path/to/webp` 指定。默认 `--jobs 2` 控制编译并行度。

## 离线归档与依赖缓存

已有以下两个归档时，可离线还原代码：

```
host-94670d961c5b6934dc8d91c7b8be68bf44b60981.tar.gz
plugin-fcb4011347ff80eeeb19e2a1f0180e13199c7c8b.tar.gz
```

```bash
python3 scripts/prepare.py --profile optimized \
  --archives-cache /path/to/source-cache \
  --dependencies-from /path/to/compatible/mlx-serve
python3 scripts/build.py --profile optimized \
  --zig /path/to/zig-0.17.0/zig --webp-prefix /path/to/webp
```

`--dependencies-from` 在隔离的 `_work/` 内引用已有原生依赖，不修改它们。它需要与锁定版本兼容的 MLX/mlx-c、Sushi、ds4、GGUF 模块、llama、Jinja 等。准备目录已存在时脚本拒绝覆盖；构建中断后可用 `--resume` 继续同一份固定源代码。

本次发布验证采用了这种离线方式，复用了原机器已经编译的原生依赖；它不等同于在第二台空白 Mac 上从网络重建全部依赖。

## 基线构建

将上述命令中的 `--profile optimized` 换成 `--profile baseline`。两者分别放在 `_work/baseline`、`_work/optimized` 和对应 `dist/` 目录。基线包含此前已有优化；优化版额外应用 `mlx-stream-selective-cache.patch`。

构建不加载模型，不修改 `iogpu`，不启动正式服务。生成文件在 `dist/`，不提交到 Git。原生库与适配库会在本地签名，构建哈希会受路径、工具链与 Mach-O 元数据影响；源码指纹与历史测速二进制哈希分别记录，不把它们混为一谈。
