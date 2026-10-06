import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.panel = dashboard.Dashboard(Path('/kit'))
        self.kit = Mock(config={'cpus': 4, 'memory_mib': 4096})
        self.kit.pid.return_value = 123
        self.kit.ssh.side_effect = lambda command: ['ssh', command]

    def test_stopped_vm_never_starts_or_runs_ssh(self):
        self.kit.pid.return_value = None
        with patch.object(dashboard, 'Kit', return_value=self.kit), patch.object(dashboard.subprocess, 'run') as run:
            self.assertFalse(self.panel.snapshot()['vm']['running'])
            run.assert_not_called(); self.kit.ssh.assert_not_called()

    def test_snapshot_coalesces_polling_and_selects_only_resource_fields(self):
        row = {name: '' for name in dashboard.FIELDS}
        row.update(ID='a' * 64, protocol='javascript:evil', polling='true')
        stats = {'ID': 'a' * 12, 'CPUPerc': '1.25%', 'MemUsage': '100MiB / 1GiB', 'extra': 'secret'}
        raw = (json.dumps(row) + '\nHC_STATS\n' + json.dumps(stats)).encode()
        with patch.object(dashboard, 'Kit', return_value=self.kit), patch.object(dashboard.subprocess, 'run', return_value=SimpleNamespace(stdout=raw)) as run:
            data = self.panel.snapshot()
            self.assertIs(data, self.panel.snapshot()); self.assertEqual(run.call_count, 1)
            container = data['containers'][0]
            self.assertEqual(container['protocol'], 'unknown')
            self.assertEqual(container['metrics']['CPUPerc'], '1.25%')
            self.assertNotIn('secret', json.dumps(data))

    def test_logs_validate_shell_input_and_bound_output(self):
        for ident, tail in (('--help', '200'), ('a' * 12 + ';id', '200'), ('a' * 12, '0'), ('a' * 12, '1001'), ('a' * 12, '2;id')):
            with self.assertRaises(ValueError): self.panel.logs(ident, tail)
        with patch.object(dashboard, 'Kit', return_value=self.kit), patch.object(dashboard.subprocess, 'run', return_value=SimpleNamespace(stdout=b'x' * (dashboard.LOG_LIMIT + 1))) as run:
            data = self.panel.logs('a' * 64, '200')
            self.assertTrue(data['truncated']); self.assertEqual(len(data['text']), dashboard.LOG_LIMIT)
            self.assertNotIn('--follow', run.call_args.args[0][-1])
