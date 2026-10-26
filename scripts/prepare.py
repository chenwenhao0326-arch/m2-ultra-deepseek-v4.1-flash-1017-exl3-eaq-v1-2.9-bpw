#!/usr/bin/env python3
"""Restore pinned sources and apply patches. Never downloads model weights."""
import argparse
import os
from pathlib import Path
import shutil
import tarfile

from common import ROOT, WORK, digest, read, run, save, verify_patch_files


def unpack(archive, destination):
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as t:
        for member in t.getmembers():
            parts = Path(member.name).parts
            if not parts or Path(member.name).is_absolute() or '..' in parts:
                raise ValueError('Unsafe archive path')
            parts = parts[1:]  # GitHub's single enclosing directory
            if not parts:
                continue
            dest = destination.joinpath(*parts)
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with t.extractfile(member) as source, dest.open('wb') as output:
                    shutil.copyfileobj(source, output)
                dest.chmod(member.mode & 0o755)
            elif member.issym():
                target = (dest.parent / member.linkname).resolve()
                try:
                    target.relative_to(destination.resolve())
                except ValueError:
                    raise ValueError('Archive symlink escapes destination')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.symlink_to(member.linkname)
            else:
                raise ValueError('Unsupported archive member: ' + member.name)


def apply(folder, name, lock):
    info = lock['patches'][name]
    patch = ROOT / 'patches' / name
    if digest(patch) != info['sha256']:
        raise ValueError('Patch fingerprint mismatch: ' + name)
    verify_patch_files(folder, info['files'], 'before')
    run(['git', '-C', folder, 'apply', '--check', patch])
    run(['git', '-C', folder, 'apply', patch])
    verify_patch_files(folder, info['files'], 'after')


def seed_dependencies(host, existing):
    """Optional local build-cache reuse; does not modify the existing checkout."""
    existing = Path(existing).resolve()
    for name in ['mlx', 'mlx-src', 'mlxc-src', 'ds4', 'sushi', 'mlx-serve-gguf',
                 'opencode2-mlx-serve', 'llama']:
        src, dest = existing / 'lib' / name, host / 'lib' / name
        if not src.exists():
            raise ValueError('Missing staged dependency: ' + str(src))
        if dest.is_dir() and not dest.is_symlink():
            dest.rmdir()  # only replace an EMPTY submodule placeholder
        if dest.exists() or dest.is_symlink():
            raise ValueError('Dependency destination exists: ' + str(dest))
        dest.symlink_to(src.resolve(), target_is_directory=True)
    jinja = host / 'lib/jinja_cpp/libjinja.a'
    if not jinja.exists():
        shutil.copy2(existing / 'lib/jinja_cpp/libjinja.a', jinja)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile', choices=['baseline', 'optimized'], default='optimized')
    ap.add_argument('--archives-cache', type=Path,
                    help='Offline directory containing the two verified source tar.gz archives')
    ap.add_argument('--dependencies-from', type=Path,
                    help='Optional existing host checkout with staged native dependencies')
    ap.add_argument('--download', action='store_true', help='Allow git source/submodule downloads')
    args = ap.parse_args()
    lock = read(ROOT / 'sources.lock.json')
    target = WORK / args.profile
    if target.exists():
        raise SystemExit('Destination exists; choose a new workspace or inspect it manually: ' + str(target))
    if not args.archives_cache and not args.download:
        raise SystemExit('Choose --archives-cache for offline preparation, or explicitly allow --download.')
    target.mkdir(parents=True)
    for key in ['host', 'plugin']:
        pin, dest = lock['upstream'][key], target / key
        if args.archives_cache:
            archive = args.archives_cache / (key + '-' + pin['commit'] + '.tar.gz')
            if digest(archive) != pin['archive_sha256']:
                raise ValueError('Source archive mismatch: ' + str(archive))
            unpack(archive, dest)
            run(['git', '-C', dest, 'init', '-q'])
        else:
            run(['git', 'clone', '--filter=blob:none', '--no-checkout',
                 'https://github.com/' + pin['repository'] + '.git', dest])
            run(['git', '-C', dest, 'checkout', '--detach', pin['commit']])
    host, plugin = target / 'host', target / 'plugin'
    apply(host, 'mlx-serve.patch', lock)
    apply(plugin, 'mlx-stream-baseline.patch', lock)
    if args.profile == 'optimized':
        apply(plugin, 'mlx-stream-selective-cache.patch', lock)
    if args.dependencies_from:
        seed_dependencies(host, args.dependencies_from)
    elif args.download:
        run(['git', '-C', host, 'submodule', 'update', '--init', '--recursive'])
    save(target / 'prepared.json', {'profile': args.profile,
         'source_lock_sha256': digest(ROOT / 'sources.lock.json'),
         'offline_archives': bool(args.archives_cache),
         'native_dependencies_reused': bool(args.dependencies_from),
         'model_downloaded': False})
    print('Prepared:', target)


if __name__ == '__main__':
    main()
