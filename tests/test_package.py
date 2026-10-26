import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from common import digest, read, verify_patch_files
from prepare import unpack
from benchmark import compare
from build import copy_private
from service import owned


class PackageTests(unittest.TestCase):
    def test_runtime_copy_does_not_modify_symlink_target_or_shared_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'upstream').write_bytes(b'original')
            (p / 'replacement').write_bytes(b'new')
            (p / 'linked').symlink_to(p / 'upstream')
            copy_private(p / 'replacement', p / 'linked')
            self.assertEqual((p / 'upstream').read_bytes(), b'original')
            self.assertFalse((p / 'linked').is_symlink())
            os.link(p / 'upstream', p / 'hardlink')
            copy_private(p / 'hardlink', p / 'hardlink')
            self.assertNotEqual((p / 'upstream').stat().st_ino, (p / 'hardlink').stat().st_ino)

    def test_reused_pid_and_unrelated_command_are_not_owned(self):
        with patch('service.ps', side_effect=lambda pid, field: 'newbirth' if field == 'lstart' else '/owned/model --serve'):
            self.assertFalse(owned(100, 'oldbirth', '/owned/model '))
        with patch('service.ps', side_effect=lambda pid, field: 'samebirth' if field == 'lstart' else '/unrelated/model --serve'):
            self.assertFalse(owned(100, 'samebirth', '/owned/model '))
        with patch('service.ps', side_effect=lambda pid, field: 'samebirth' if field == 'lstart' else '/owned/model --serve'):
            self.assertTrue(owned(100, 'samebirth', '/owned/model '))

    def test_published_patch_and_adapter_hashes(self):
        lock = read(ROOT / 'sources.lock.json')
        for name, item in lock['patches'].items():
            self.assertEqual(digest(ROOT / 'patches' / name), item['sha256'])
        self.assertEqual(digest(ROOT / 'm2/kernel_patch.c'), lock['m2_adapter']['source_sha256'])

    def test_expert_fixture_is_only_fixed_size_numeric_rates(self):
        s = read(ROOT / 'config/expert-tally.json')
        self.assertEqual((s['layers'], s['experts']), (40, 384))
        self.assertTrue(all(len(row) == 384 for row in s['rates']))
        values = [v for row in s['rates'] for v in row]
        self.assertTrue(all(0 <= v <= 1 for v in values))
        data = struct.pack('<8s4I', b'MLXSTALY', s['version'], 40, 384, s['window']) + struct.pack('<15360f', *values)
        self.assertEqual(hashlib.sha256(data).hexdigest(), s['sha256'])

    def test_source_mismatch_and_missing_new_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'a').write_text('original')
            item = {'path': 'a', 'before': digest(p / 'a'), 'after': None}
            verify_patch_files(p, [item], 'before')
            (p / 'a').write_text('changed')
            with self.assertRaises(ValueError):
                verify_patch_files(p, [item], 'before')
            with self.assertRaises(ValueError):
                verify_patch_files(p, [item], 'after')

    def test_archive_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'bad.tar'
            with tarfile.open(archive, 'w') as t:
                member = tarfile.TarInfo('prefix/../../escape')
                member.size = 1
                t.addfile(member, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                unpack(archive, root / 'out')
            self.assertFalse((root / 'escape').exists())

    def test_profile_does_not_enable_unqualified_experiments(self):
        p = read(ROOT / 'config/profile.json')
        self.assertEqual((p['prefill_rows'], p['decode_rows'], p['context_tokens']), (224, 288, 262144))
        for key in ['DSV41_EXPERIMENT_FRESH_PARK_STATS', 'DSV41_EXPERIMENT_WIDE_PARTIAL_PARK',
                    'DSV41_EXPERIMENT_FULL_Q', 'DSV41_EXPERIMENT_GU_PREFIX']:
            self.assertEqual(p['environment'][key], '0')

    def test_historical_evidence_does_not_omit_ttft_or_changed_outputs(self):
        d = read(ROOT / 'benchmarks/m2-ultra-224-288-20261026.json')
        a, b = d['runs']
        for x, y in zip(a['requests'], b['requests']):
            self.assertEqual(x['output_sha256'], y['output_sha256'])
            self.assertEqual(x['request_sha256'], y['request_sha256'])
            self.assertGreater(x['ttft_s'], 0)
            self.assertGreater(y['ttft_s'], 0)
        self.assertGreater(a['requests'][0]['timings']['predicted_per_second'], 0)

    def test_comparison_rejects_mismatched_conditions(self):
        a = {'arm': 'A', 'rows': [224, 288], 'context_tokens': 262144, 'tokens': 1024, 'followup_tokens': 512, 'requests': []}
        b = dict(a, arm='B', tokens=512)
        with self.assertRaises(ValueError):
            compare(a, b)


if __name__ == '__main__':
    unittest.main()
