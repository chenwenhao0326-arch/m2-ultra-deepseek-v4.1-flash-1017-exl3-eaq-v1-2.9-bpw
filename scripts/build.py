#!/usr/bin/env python3
"""Build the pinned source and M2 shim; no model loading or system tuning."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import time

from common import ROOT, WORK, clean_environment, digest, read, run, save, verify_patch_files


def copy_private(source, dest):
    """Never follow an installed destination symlink or modify a shared inode."""
    temp = dest.with_name(dest.name + '.copying')
    shutil.copyfile(source, temp)
    temp.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
    temp.replace(dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile', choices=['baseline', 'optimized'], default='optimized')
    ap.add_argument('--zig', type=Path)
    ap.add_argument('--webp-prefix', type=Path)
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--resume', action='store_true', help='Resume an interrupted/failed build with the same pinned sources')
    args = ap.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise SystemExit('This build recipe targets Apple Silicon macOS only.')
    base = WORK / args.profile
    prepared = read(base / 'prepared.json')
    if prepared['source_lock_sha256'] != digest(ROOT / 'sources.lock.json'):
        raise SystemExit('Source lock changed after preparation.')
    host, plugin = base / 'host', base / 'plugin'
    lock = read(ROOT / 'sources.lock.json')
    verify_patch_files(host, lock['patches']['mlx-serve.patch']['files'], 'after')
    merged = {x['path']: x for x in lock['patches']['mlx-stream-baseline.patch']['files']}
    if args.profile == 'optimized':
        merged.update({x['path']: x for x in lock['patches']['mlx-stream-selective-cache.patch']['files']})
    verify_patch_files(plugin, list(merged.values()), 'after')
    zig = (args.zig or Path(os.environ.get('ZIG', shutil.which('zig') or str(host / '.zig-toolchain/zig')))).resolve()
    if subprocess.check_output([str(zig), 'version'], text=True).strip() != '0.17.0':
        raise SystemExit('Use the pinned Zig0.17.0 toolchain.')
    dest = ROOT / 'dist' / args.profile
    if dest.exists():
        if not args.resume or not (dest / 'build.json').exists():
            raise SystemExit('Build destination exists; use --resume only for this package build.')
        previous = read(dest / 'build.json')
        if previous.get('status') == 'built' or previous.get('source_lock_sha256') != digest(ROOT / 'sources.lock.json'):
            raise SystemExit('Already built, or source lock changed; preserve this destination.')
        save(dest / ('prior-build-%d.json' % time.time_ns()), previous)
    else:
        dest.mkdir(parents=True)
    cmd = [str(zig), 'build', '-j' + str(args.jobs), '-Doptimize=ReleaseFast',
           '-Dplugin-profile=true', '-Dversion=26.10.26-public-' + args.profile,
           '-Dmlx-stream-dir=' + str(plugin), '--prefix', str(dest), '--summary', 'all']
    if args.webp_prefix:
        cmd.append('-Dwebp-prefix=' + str(args.webp_prefix.resolve()))
    receipt = {'status': 'building', 'command': cmd, 'profile': args.profile,
               'source_lock_sha256': digest(ROOT / 'sources.lock.json'), 'model_loaded': False}
    save(dest / 'build.json', receipt)
    start = time.monotonic()
    try:
        run(cmd, cwd=host, env=clean_environment())
        libs = dest / 'lib'
        libs.mkdir(exist_ok=True)
        for source in [host / 'lib/mlx/lib', host / 'lib/llama/lib']:
            for file in source.iterdir():
                if file.is_file() and file.suffix in ('.dylib', '.metallib'):
                    copy_private(file, libs / file.name)
        webp = args.webp_prefix
        if webp is None:
            webp = Path(subprocess.check_output(['brew', '--prefix', 'libwebp'], text=True).strip())
        for file in (webp / 'lib').glob('*.dylib'):
            copy_private(file, libs / file.name)
        # A staged formula may keep only libwebp.dylib while its install ID is
        # libwebp.7.dylib. Preserve install-name aliases in the private bundle.
        for library in list(libs.glob('*.dylib')):
            ids = subprocess.check_output(['otool', '-D', str(library)], text=True).splitlines()[1:]
            for ident in ids:
                alias = libs / Path(ident.strip()).name
                if alias.name != library.name and not alias.exists():
                    alias.symlink_to(library.name)
        shim = dest / 'libm2_exl3.dylib'
        run(['/usr/bin/clang', '-dynamiclib', '-O2', '-mmacosx-version-min=26.2',
             ROOT / 'm2/kernel_patch.c', '-L' + str(libs), '-lmlxc',
             '-Wl,-rpath,@loader_path/lib', '-o', shim])
        # Make runtime library references portable within this build directory.
        artifacts = [dest / 'bin/mlx-serve', shim] + list(libs.glob('*.dylib'))
        for artifact in artifacts:
            # Zig installation may use read-only files or shared build-cache inodes.
            copy_private(artifact, artifact)
            text = subprocess.check_output(['otool', '-L', str(artifact)], text=True)
            for line in text.splitlines()[1:]:
                dep = line.strip().split(' (', 1)[0]
                if dep.startswith('/') and (libs / Path(dep).name).exists():
                    run(['install_name_tool', '-change', dep, '@rpath/' + Path(dep).name, artifact])
            run(['codesign', '--force', '--sign', '-', artifact])
        receipt.update(status='built', elapsed_s=time.monotonic() - start,
                       binary_sha256=digest(dest / 'bin/mlx-serve'), shim_sha256=digest(shim))
    except BaseException as e:
        receipt.update(status='failed', error=repr(e), elapsed_s=time.monotonic() - start)
        raise
    finally:
        save(dest / 'build.json', receipt)
    print('Built:', dest)


if __name__ == '__main__':
    main()
