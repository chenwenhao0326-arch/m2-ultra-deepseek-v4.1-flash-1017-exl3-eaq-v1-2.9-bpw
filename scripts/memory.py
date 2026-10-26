#!/usr/bin/env python3
"""Sample the managed inference process footprint and system swap locally."""
import argparse
import ctypes
import datetime
import json
import os
import pathlib
import re
import signal
import struct
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent
GIB = 1024 ** 3


def process_budget_bytes(data):
    # These overlap: use the largest accounting view, never sum them.
    return max(data['footprint_bytes'], data['resident_bytes'], data['wired_bytes'])


def guard_reason(data, process_limit_gib, process_samples, critical_samples,
                 process_grace=5, critical_grace=10):
    if process_samples >= process_grace:
        return 'managed process memory exceeded %.1f GiB for %d samples' % (process_limit_gib, process_samples)
    if critical_samples >= critical_grace:
        return 'kernel memory pressure stayed critical for %d samples' % critical_samples
    return None


def owned_process(pid, binary):
    command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='],
                             capture_output=True, text=True).stdout.strip()
    return command.startswith(str(binary) + ' ')


def stop_owned(pid, binary):
    if not owned_process(pid, binary):
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(12):
        if not owned_process(pid, binary):
            return
        time.sleep(.25)
    if owned_process(pid, binary):
        os.kill(pid, signal.SIGKILL)


def process_memory(pid):
    lib = ctypes.CDLL('/usr/lib/libproc.dylib')
    lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    lib.proc_pid_rusage.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(4096)
    if lib.proc_pid_rusage(pid, 4, ctypes.byref(buffer)) != 0:
        return None
    def value(index):
        return struct.unpack_from('=Q', buffer.raw, 16 + 8 * index)[0]
    return {'footprint_bytes': value(7), 'lifetime_peak_footprint_bytes': value(28),
            'resident_bytes': value(6), 'wired_bytes': value(5),
            'disk_read_bytes': value(16), 'disk_written_bytes': value(17)}


def swap_memory():
    raw = subprocess.check_output(['sysctl', '-n', 'vm.swapusage'], text=True)
    result = {}
    for key, number, unit in re.findall(r'(total|used|free)\s*=\s*([0-9.]+)([KMG])', raw):
        result[key + '_bytes'] = float(number) * {'K': 1024, 'M': 1024**2, 'G': 1024**3}[unit]
    return result


def system_memory():
    raw = subprocess.check_output(['vm_stat'], text=True)
    match = re.search(r'page size of (\d+) bytes', raw)
    page_size = int(match.group(1)) if match else 16384
    names = {'Pages wired down': 'wired_bytes', 'Pages occupied by compressor': 'compressed_bytes',
             'File-backed pages': 'file_cache_bytes', 'Anonymous pages': 'anonymous_bytes'}
    result = {}
    for label, field in names.items():
        match = re.search(re.escape(label) + r':\s*(\d+)', raw)
        if match:
            result[field] = int(match.group(1)) * page_size
    pressure = subprocess.run(['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'],
                              capture_output=True, text=True)
    try:
        result['pressure_level'] = int(pressure.stdout.strip()) if pressure.returncode == 0 else None
    except ValueError:
        result['pressure_level'] = None
    return result

