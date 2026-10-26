"""Small, dependency-free helpers for the reproducible experiment package."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '_work'


def read(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def run(argv, cwd=None, env=None):
    print('+', ' '.join(map(str, argv)), flush=True)
    subprocess.run(list(map(str, argv)), cwd=cwd, env=env, check=True)


def clean_environment():
    return {k: v for k, v in os.environ.items()
            if not k.startswith(('DYLD_', 'MLX_', 'DSV41_', 'MTPLX_', 'DS4_'))}


def verify_patch_files(folder, entries, side):
    for entry in entries:
        name = entry['path']
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe patch path')
        path = folder / name
        expected = entry[side]
        if expected is None:
            if path.exists():
                raise ValueError('Unexpected file: ' + name)
        elif not path.is_file() or digest(path) != expected:
            raise ValueError('Source fingerprint mismatch: ' + name)
