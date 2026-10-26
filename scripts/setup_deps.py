#!/usr/bin/env python3
"""Explicit dependency-download step, separate from building or starting a model."""
import argparse
import shutil
import subprocess

from common import ROOT, WORK, read, run


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profile', choices=['baseline', 'optimized'], default='optimized')
    ap.add_argument('--allow-downloads', action='store_true')
    args = ap.parse_args()
    if not args.allow_downloads:
        raise SystemExit('This step downloads source/toolchain/native-library dependencies. Pass --allow-downloads explicitly. It never downloads model weights.')
    host = WORK / args.profile / 'host'
    prepared = read(host.parent / 'prepared.json')
    if prepared['offline_archives']:
        raise SystemExit('For archive mode, use --dependencies-from with a compatible staged checkout. Online setup needs the pinned git checkout.')
    for tool in ['cmake', 'node', 'brew']:
        if not shutil.which(tool):
            raise SystemExit('Missing ' + tool + '. See docs/BUILD.md.')
    run(['git', '-C', host, 'submodule', 'update', '--init', '--recursive'])
    run(['bash', 'scripts/fetch-zig.sh'], cwd=host)
    run(['bash', 'scripts/fetch-llama.sh'], cwd=host)
    run(['bash', 'scripts/build-mlx.sh'], cwd=host)
    # Host vendor ships Jinja sources; rebuilding is harmless and avoids relying on a tracked archive.
    jinja = host / 'lib/jinja_cpp'
    objects = jinja / 'obj'
    objects.mkdir(exist_ok=True)
    names = ['jinja_wrapper', 'caps', 'lexer', 'parser', 'runtime', 'jinja_string', 'value']
    for name in names:
        run(['clang++', '-std=c++17', '-O2', '-DNDEBUG', '-I', jinja, '-c', jinja / (name + '.cpp'), '-o', objects / (name + '.o')])
    run(['ar', 'rcs', jinja / 'libjinja.a'] + [objects / (name + '.o') for name in names])
    print('Dependencies staged. Next: python3 scripts/build.py --profile', args.profile)


if __name__ == '__main__':
    main()
