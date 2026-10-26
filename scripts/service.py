#!/usr/bin/env python3
"""Isolated localhost service with explicit profile, logs and owned-process guards."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.request

from common import ROOT, clean_environment, digest, read, save
import memory

LOCAL = ROOT / '.local'
STATE = LOCAL / 'service.json'
GIB = 1 << 30


def node_binary():
    return os.environ.get('NODE_BINARY') or shutil.which('node')


def now():
    return datetime.datetime.now().astimezone().isoformat()


def ps(pid, field):
    if not isinstance(pid, int) or pid < 2:
        return ''
    return subprocess.run(['ps', '-p', str(pid), '-o', field + '='],
                          capture_output=True, text=True).stdout.strip()


def owned(pid, birth, prefix):
    return bool(birth) and ps(pid, 'lstart') == birth and ps(pid, 'command').startswith(prefix)


def status():
    s = read(STATE) if STATE.exists() else {'state': 'stopped'}
    s['supervisor_alive'] = owned(s.get('supervisor_pid'), s.get('supervisor_birth'), s.get('supervisor_command', ''))
    s['engine_alive'] = owned(s.get('engine_pid'), s.get('engine_birth'), s.get('engine_command', ''))
    return s


def model_check(model, profile):
    for name, expected in profile['model_header_sha256'].items():
        if not (model / name).is_file() or digest(model / name) != expected:
            raise ValueError('Wrong or incomplete pinned model pack: ' + name)


def materialize_runtime(model, profile, run_dir):
    stats = read(ROOT / 'config/expert-tally.json')
    values = [v for layer in stats['rates'] for v in layer]
    raw = struct.pack('<8s4I', b'MLXSTALY', stats['version'], stats['layers'], stats['experts'], stats['window'])
    raw += struct.pack('<' + str(len(values)) + 'f', *values)
    identity = profile['environment']['MLX_STREAM_EXPERT_TALLY_IDENTITY']
    tally = run_dir / 'tally' / identity / ('w' + str(stats['window'])) / ('deepseek_v41-' + model.name) / 'expert-tally.bin'
    tally.parent.mkdir(parents=True, exist_ok=True)
    tally.write_bytes(raw)
    if digest(tally) != stats['sha256']:
        raise ValueError('Expert-rate fixture reconstruction mismatch')
    settings = run_dir / 'model-settings.json'
    save(settings, {str(model): {'expert_resident_ratio': 0.25,
                               'expert_tally_window': 32, 'expert_tally_file': 'pinned'}})
    return settings, run_dir / 'tally'


def recipe(model, profile_name, front_port, backend_port, run_dir):
    profile = read(ROOT / 'config/profile.json')
    dist = ROOT / 'dist' / profile_name
    build = read(dist / 'build.json')
    binary, shim = dist / 'bin/mlx-serve', dist / 'libm2_exl3.dylib'
    if build.get('status') != 'built' or digest(binary) != build['binary_sha256'] or digest(shim) != build['shim_sha256']:
        raise ValueError('Build receipt or executable mismatch')
    model_check(model, profile)
    settings, tally = materialize_runtime(model, profile, run_dir)
    env = clean_environment()
    for key in list(env):
        if 'proxy' in key.lower():
            del env[key]
    env.update(profile['environment'])
    on = '1' if profile_name == 'optimized' else '0'
    env.update(DSV41_EXPERIMENT_PARK224288=on, DSV41_EXPERIMENT_PARTIAL_PARK=on,
               DYLD_INSERT_LIBRARIES=str(shim), DYLD_LIBRARY_PATH=str(dist / 'lib'),
               MLX_SERVE_MODEL_SETTINGS_PATH=str(settings), MLX_STREAM_EXPERT_TALLY_ROOT=str(tally),
               DSV41_SESSION_DISK_ROOT=str(LOCAL / 'native-cache' / profile_name),
               DSV41_SESSION_DISK_ID=build['binary_sha256'])
    command = [str(binary), '--serve', '--model', str(model), '--host', '127.0.0.1',
               '--port', str(backend_port), '--ctx-size', str(profile['context_tokens']),
               '--wired-margin-gib', '2', '--os-reserve-gib', '8', '--no-decode-attn-quant',
               '--kv-quant', 'off', '--no-pld', '--max-resident-models', '1', '--max-tokens', '4096',
               '--timeout', '1800', '--idle-evict-secs', str(profile['idle_evict_seconds']),
               '--metrics', '--log-file', 'off', '--no-vision', '--top-p', '0.95']
    return profile, command, env


def doctor(model=None):
    result = {'platform': platform.system(), 'architecture': platform.machine(), 'node': node_binary()}
    if platform.system() == 'Darwin':
        for key in ['hw.memsize', 'machdep.cpu.brand_string', 'iogpu.wired_limit_mb']:
            result[key] = subprocess.check_output(['sysctl', '-n', key], text=True).strip()
    if model:
        model_check(model.resolve(), read(ROOT / 'config/profile.json'))
        result['model_header_pins'] = 'matched (not a full418GBweight hash pass)'
    return result


def check_start(args):
    info = doctor(args.model)
    if args.port == args.backend_port:
        raise ValueError('Frontend and backend ports must be different.')
    if 'Apple M2' not in info.get('machdep.cpu.brand_string', '') or int(info.get('hw.memsize', 0)) < 192 * GIB:
        raise ValueError('The published224/288profile is qualified only on M2Ultra192GiB.')
    if not info['node']:
        raise ValueError('Node.js18+ is required for the streaming frontend proxy.')
    if int(info.get('iogpu.wired_limit_mb', 0)) < 184320:
        raise ValueError('GPU allowance below the tested profile. Read docs/OPERATIONS.md; this tool does not alter system settings.')
    for port in [args.port, args.backend_port]:
        if not 1 <= port <= 65535:
            raise ValueError('Invalid TCP port')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    return info


def terminate(child):
    if child and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def supervise(args):
    LOCAL.mkdir(exist_ok=True)
    lock = (LOCAL / 'service.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    run_dir = LOCAL / 'logs' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    run_dir.mkdir(parents=True, exist_ok=False)
    state = {'state': 'starting', 'started_at': now(), 'profile': args.profile,
             'rows': [224, 288], 'context_tokens': 262144, 'front_port': args.port,
             'supervisor_pid': os.getpid(), 'supervisor_birth': ps(os.getpid(), 'lstart'),
             'supervisor_command': ps(os.getpid(), 'command'), 'log_directory': str(run_dir)}
    save(STATE, state)
    engine = proxy = None
    stopped = False
    def stop_signal(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    try:
        check_start(args)
        profile, command, env = recipe(args.model.resolve(), args.profile, args.port, args.backend_port, run_dir)
        state['command'] = command
        state['environment'] = {k: v for k, v in env.items() if k.startswith(('DSV41_', 'MLX_', 'DYLD_'))}
        swap0 = memory.swap_memory()['used_bytes']
        with (run_dir / 'server.log').open('wb') as log:
            engine = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        state.update(engine_pid=engine.pid, engine_birth=ps(engine.pid, 'lstart'), engine_command=command[0] + ' ')
        proxy_env = dict(os.environ, MLX_STUDIO_FRONT_PORT=str(args.port), MLX_STUDIO_BACK_PORT=str(args.backend_port))
        with (run_dir / 'frontend.log').open('wb') as log:
            proxy = subprocess.Popen([node_binary(), str(ROOT / 'web/proxy.mjs')], env=proxy_env, stdout=log, stderr=log)
        save(STATE, state)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with (run_dir / 'memory.jsonl').open('w') as samples:
            while not stopped and engine.poll() is None and proxy.poll() is None:
                own = memory.process_memory(engine.pid)
                system, swap = memory.system_memory(), memory.swap_memory()
                reason = None
                if own and memory.process_budget_bytes(own) > profile['process_limit_gib'] * GIB:
                    reason = 'process180GiB'
                if sum(system[k] for k in ['wired_bytes', 'anonymous_bytes', 'compressed_bytes']) > profile['host_limit_gib'] * GIB:
                    reason = 'host190GiB'
                if system.get('pressure_level') != 1:
                    reason = 'memory pressure'
                if swap['used_bytes'] - swap0 > 256 * (1 << 20):
                    reason = 'swap grew more than256MiB'
                samples.write(json.dumps({'time': now(), 'process': own, 'system': system, 'swap': swap, 'guard': reason}) + '\n')
                samples.flush()
                if reason:
                    state.update(state='stopped_by_guard', error=reason)
                    break
                if state['state'] == 'starting':
                    try:
                        with opener.open('http://127.0.0.1:%d/v1/models' % args.backend_port, timeout=1) as response:
                            if response.status == 200:
                                state.update(state='ready', ready_at=now())
                                save(STATE, state)
                    except OSError:
                        pass
                time.sleep(1)
    except BaseException as error:
        state.update(state='failed', error=str(error))
    finally:
        if state['state'] in ['ready', 'starting']:
            state['state'] = 'stopped' if stopped else 'exited'
        terminate(proxy)
        terminate(engine)
        state['stopped_at'] = now()
        save(STATE, state)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['doctor', 'start', 'stop', 'status', '_supervise'])
    ap.add_argument('--model', type=Path)
    ap.add_argument('--profile', choices=['baseline', 'optimized'], default='optimized')
    ap.add_argument('--port', type=int, default=18000)
    ap.add_argument('--backend-port', type=int, default=18002)
    args = ap.parse_args()
    if args.action == 'doctor':
        print(json.dumps(doctor(args.model), indent=2)); return
    if args.action == 'status':
        print(json.dumps(status(), indent=2)); return
    if args.action == 'stop':
        s = status()
        if s['supervisor_alive']:
            os.kill(s['supervisor_pid'], signal.SIGTERM)
            for _ in range(100):
                if not status()['supervisor_alive']:
                    break
                time.sleep(.2)
            if status()['supervisor_alive']:
                raise SystemExit('Supervisor is still stopping; inspect its logs before retrying.')
        print(json.dumps(status(), indent=2)); return
    if args.model is None:
        raise SystemExit('--model is required; weights are never downloaded automatically.')
    if args.action == '_supervise':
        supervise(args); return
    if status()['supervisor_alive']:
        raise SystemExit('This package already has a live service.')
    check_start(args)
    LOCAL.mkdir(exist_ok=True)
    with (LOCAL / 'supervisor.log').open('ab') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_supervise',
            '--model', str(args.model.resolve()), '--profile', args.profile,
            '--port', str(args.port), '--backend-port', str(args.backend_port)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    print(json.dumps({'supervisor_pid': child.pid, 'state': 'starting',
                      'url': 'http://127.0.0.1:%d/' % args.port, 'check': 'python3 scripts/service.py status'}))


if __name__ == '__main__':
    main()
