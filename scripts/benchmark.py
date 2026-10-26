#!/usr/bin/env python3
"""Record one controlled arm. Run baseline A freshly before optimized B."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

from common import ROOT, read, save
from service import status

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PROMPTS = [
    ('text', '请面向后端工程师详细解释DNS、TCP、TLS和HTTP在打开一个HTTPS网页时各自做什么，连接复用如何降低延迟，缓存在哪些步骤生效。用具体例子，至少1000字。'),
    ('code', '只输出Python代码，实现一个有界异步任务池，使用asyncio.Semaphore限制并发，保留输入顺序返回结果，支持单任务超时和错误收集，并给出可运行的演示。实现完整，不调用工具。'),
]
FOLLOWUP = '为上面的异步任务池补充一组unittest.IsolatedAsyncioTestCase测试，覆盖并发上限、返回顺序、超时和异常。只输出Python代码，不调用工具。'


def get(url):
    with OPENER.open(url, timeout=10) as response:
        return response.read()


def request(url, model, label, messages, cap, seed):
    payload = {'model': model, 'messages': messages, 'thinking': {'type': 'disabled'},
               'temperature': 1.0, 'top_p': .95, 'seed': seed, 'max_tokens': cap,
               'stream': True, 'stream_options': {'include_usage': True}}
    result = {'label': label, 'request': payload, 'chunks': [], 'content': '', 'reasoning': '',
              'usage': {}, 'timings': {}, 'ttft_s': None, 'status': 'running'}
    start = time.monotonic()
    try:
        req = urllib.request.Request(url + '/v1/chat/completions',
                    data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        with OPENER.open(req, timeout=300) as response:
            for raw in response:
                if not raw.startswith(b'data: '):
                    continue
                line = raw[6:].strip()
                if line == b'[DONE]':
                    break
                chunk = json.loads(line)
                result['chunks'].append(chunk)
                if chunk.get('error'):
                    raise RuntimeError(str(chunk['error']))
                for choice in chunk.get('choices', []):
                    delta = choice.get('delta', {})
                    text = delta.get('content') or ''
                    if text and result['ttft_s'] is None:
                        result['ttft_s'] = time.monotonic() - start
                    result['content'] += text
                    result['reasoning'] += delta.get('reasoning_content') or ''
                    if choice.get('finish_reason'):
                        result['finish_reason'] = choice['finish_reason']
                for key in ['usage', 'timings']:
                    if chunk.get(key):
                        result[key] = chunk[key]
        if not result['content'] or result['reasoning'] or not result['usage'].get('completion_tokens'):
            raise RuntimeError('Incomplete/non-thinking response contract failed')
        result['status'] = 'complete'
    except BaseException as e:
        result.update(status='failed', error=str(e))
    result['elapsed_s'] = time.monotonic() - start
    result['request_sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    result['output_sha256'] = hashlib.sha256(result['content'].encode()).hexdigest()
    return result


def compare(a, b):
    if a['arm'] != 'A' or b['arm'] != 'B':
        raise ValueError('Compare a freshly measured baseline A with optimized B.')
    keys = ['rows', 'context_tokens', 'tokens', 'followup_tokens']
    if any(a[k] != b[k] for k in keys):
        raise ValueError('Configuration mismatch; do not attribute a speed difference.')
    allowed_changes = {'DSV41_EXPERIMENT_PARK224288', 'DSV41_EXPERIMENT_PARTIAL_PARK',
                       'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'MLX_SERVE_MODEL_SETTINGS_PATH',
                       'MLX_STREAM_EXPERT_TALLY_ROOT', 'DSV41_SESSION_DISK_ROOT', 'DSV41_SESSION_DISK_ID'}
    ea = a.get('service', {}).get('environment', {})
    eb = b.get('service', {}).get('environment', {})
    for key in set(ea) | set(eb):
        if key not in allowed_changes and ea.get(key) != eb.get(key):
            raise ValueError('Runtime flags differ: ' + key)
    result = []
    if len(a['requests']) != 3 or len(b['requests']) != 3:
        raise ValueError('Both arms must complete all three requests.')
    for x, y in zip(a['requests'], b['requests']):
        if x['request_sha256'] != y['request_sha256']:
            raise ValueError('Request payloads differ: ' + x['label'])
        result.append({'case': x['label'], 'same_output': x['output_sha256'] == y['output_sha256'],
                       'tps': [x['timings']['predicted_per_second'], y['timings']['predicted_per_second']],
                       'elapsed_s': [x['elapsed_s'], y['elapsed_s']]})
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--arm', choices=['A', 'B'], required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--compare', type=Path)
    ap.add_argument('--tokens', type=int, default=1024)
    args = ap.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists; preserve it and choose a new filename.')
    s = status()
    expected = 'baseline' if args.arm == 'A' else 'optimized'
    if not s.get('engine_alive') or s.get('profile') != expected:
        raise SystemExit('Start this package with --profile ' + expected + ' first.')
    url = 'http://127.0.0.1:%d' % s['front_port']
    metrics = get(url + '/metrics').decode()
    for name in ['vllm:num_requests_running', 'vllm:num_requests_waiting']:
        if not re.search(r'^' + re.escape(name) + r' 0\s*$', metrics, re.M):
            raise SystemExit('Service is busy or metrics are unavailable; wait, do not interrupt.')
    model = json.loads(get(url + '/v1/models'))['data'][0]['id']
    report = {'status': 'running', 'arm': args.arm, 'rows': [224, 288],
              'context_tokens': 262144, 'tokens': args.tokens, 'followup_tokens': min(args.tokens, 512),
              'service': s, 'started_epoch': time.time(), 'requests': [],
              'notes': 'Independent contexts for text/code; followup uses exact code answer. No retries based on answer.'}
    save(args.output, report)
    warmup = request(url, model, 'warmup', [{'role': 'user', 'content': '请从1写到30，用逗号分隔，不加解释。'}], 80, 123)
    report['warmup'] = warmup
    if warmup['status'] != 'complete':
        report.update(status='failed', error='Warmup failed'); save(args.output, report); return 1
    for label, prompt in PROMPTS:
        result = request(url, model, label, [{'role': 'user', 'content': prompt}], args.tokens, 42)
        report['requests'].append(result); save(args.output, report)
        if result['status'] != 'complete':
            report['status'] = 'failed'; save(args.output, report); return 1
    code = report['requests'][-1]
    history = code['request']['messages'] + [{'role': 'assistant', 'content': code['content']}, {'role': 'user', 'content': FOLLOWUP}]
    result = request(url, model, 'followup', history, min(args.tokens, 512), 43)
    report['requests'].append(result)
    report['status'] = result['status']
    report['finished_epoch'] = time.time()
    report['memory_log'] = str(Path(s['log_directory']) / 'memory.jsonl')
    if args.compare and report['status'] == 'complete':
        report['comparison'] = compare(read(args.compare), report)
    save(args.output, report)
    print(json.dumps({'status': report['status'], 'comparison': report.get('comparison'), 'output': str(args.output)}, indent=2))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
