import json
from contextlib import nullcontext
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
        row.update(ID='a' * 64, protocol='javascript:evil', polling='true', project='demo', service='web')
        stats = {'ID': 'a' * 12, 'CPUPerc': '1.25%', 'MemUsage': '100MiB / 1GiB', 'extra': 'secret'}
        mount = {'ID': 'a' * 64, 'image_id': 'sha256:' + 'b' * 64, 'mounts': [{'Type': 'volume', 'Name': 'demo-data', 'Destination': '/data', 'RW': True, 'Source': '/private'}]}
        image = {'ID': mount['image_id'], 'Repository': 'demo', 'Tag': 'latest', 'CreatedAt': '', 'Size': '1MB'}
        volume = {'Name': 'demo-data', 'Driver': 'local', 'Scope': 'local', 'project': 'demo'}
        raw = (json.dumps(row) + '\nHC_IMAGES\n' + json.dumps(image) + '\nHC_VOLUMES\n' + json.dumps(volume) + '\nHC_MOUNTS\n' + json.dumps(mount) + '\nHC_STATS\n' + json.dumps(stats) + '\nHC_MEMORY\n3925000\n').encode()
        with patch.object(dashboard, 'Kit', return_value=self.kit), patch.object(dashboard.threading, 'Thread'), patch.object(dashboard.subprocess, 'run', return_value=SimpleNamespace(stdout=raw)) as run:
            data = self.panel.snapshot()
            self.assertIs(data, self.panel.snapshot()); self.assertEqual(run.call_count, 1)
            container = data['containers'][0]
            self.assertEqual(container['protocol'], 'unknown')
            self.assertEqual(container['metrics']['CPUPerc'], '1.25%')
            self.assertNotIn('secret', json.dumps(data))
            self.assertEqual(container['project'], 'demo')
            self.assertEqual(data['volumes'][0]['containers'], [''])
            self.assertEqual(data['images'][0]['containers'], [''])
            self.assertNotIn('/private', json.dumps(data))
            self.assertEqual(data['resources']['cpu_capacity_percent'], 400)
            self.assertEqual(data['resources']['memory_used_bytes'], 100 * 1024**2)

    def test_deletion_requires_matching_confirmation_and_refuses_used_objects(self):
        image_id = 'sha256:' + 'b' * 64
        image = {'ID': image_id, 'Repository': 'demo', 'Tag': 'latest', 'containers': []}
        volume = {'Name': 'demo-data', 'containers': []}
        inventory = {'vm': {'running': True}, 'error': None, 'containers': [], 'images': [image], 'volumes': [volume]}
        with patch.object(self.panel, 'snapshot', return_value=inventory), patch.object(dashboard.threading, 'Thread') as worker:
            for value in ({'action':'delete','kind':'volume','id':'demo-data'}, {'action':'delete','kind':'volume','id':'../../data','confirm':'../../data'}, {'action':'delete','kind':'image','id':image_id,'reference':'other:latest','confirm':'other:latest'}):
                with self.assertRaises(ValueError): self.panel.action(value)
            volume['containers'] = ['stopped-container']
            with self.assertRaises(ValueError): self.panel.action({'action':'delete','kind':'volume','id':'demo-data','confirm':'demo-data'})
            image['containers'] = ['stopped-container']
            with self.assertRaises(ValueError): self.panel.action({'action':'delete','kind':'image','id':image_id,'reference':'demo:latest','confirm':'demo:latest'})
            worker.assert_not_called()
            volume['containers'] = []
            self.panel.action({'action':'delete','kind':'volume','id':'demo-data','confirm':'demo-data'})
            self.assertEqual(worker.call_args.kwargs['args'][1:4], (['demo-data'], 'delete', 'volume'))

    def test_container_delete_requires_stopped_state_and_name_confirmation(self):
        ident = 'a' * 64
        container = {'ID': ident, 'Names': 'demo-web', 'State': 'running'}
        inventory = {'vm': {'running': True}, 'error': None, 'containers': [container]}
        with patch.object(self.panel, 'snapshot', return_value=inventory), patch.object(dashboard.threading, 'Thread') as worker:
            value = {'action': 'delete', 'kind': 'container', 'id': ident, 'confirm': 'demo-web'}
            with self.assertRaises(ValueError): self.panel.action(value)
            container['State'] = 'exited'
            with self.assertRaises(ValueError): self.panel.action(dict(value, confirm='other'))
            worker.assert_not_called()
            self.panel.action(value)
            self.assertEqual(worker.call_args.kwargs['args'][1:4], ([ident], 'delete', 'container'))

    def test_container_delete_preserves_volumes_and_uses_no_force(self):
        self.panel.jobs['test'] = {'status': 'running'}
        with patch.dict(sys.modules, idle=SimpleNamespace(activity=lambda kit: nullcontext())), patch.object(dashboard, 'Kit', return_value=self.kit), patch.object(dashboard.subprocess, 'run') as run:
            self.panel._perform('test', ['a' * 64], 'delete', 'container')
            self.assertEqual(run.call_args.args[0][-1], 'docker container rm -- ' + 'a' * 64)
            self.assertEqual(self.panel.jobs['test']['status'], 'done')

    def test_storage_reports_sizes_without_exposing_raw_docker_metadata(self):
        raw = (json.dumps({'Images':[{'ID':'image','SharedSize':'1MB','UniqueSize':'2MB'}], 'Volumes':[{'Name':'data','Size':'48.3MB','Labels':'secret'}]}) + '\nHC_VOLUME_META\n' + json.dumps({'Name':'data','CreatedAt':'2026-10-06T00:00:00Z'})).encode()
        with patch.object(dashboard, 'Kit', return_value=self.kit), patch.object(dashboard.subprocess, 'run', return_value=SimpleNamespace(stdout=raw)):
            self.panel._storage_update()
        self.assertEqual(self.panel.storage_data['volumes']['data']['size_bytes'], 48300000)
        self.assertNotIn('secret', json.dumps(self.panel.storage_data))

    def test_actions_resolve_only_own_inventory_ids_and_never_shell_project_names(self):
        ident = 'a' * 64
        inventory = {'vm': {'running': True}, 'error': None, 'containers': [{'ID': ident, 'project': 'demo;echo bad'}]}
        with patch.object(self.panel, 'snapshot', return_value=inventory), patch.object(dashboard.threading, 'Thread') as worker:
            for value in ({'action': 'exec', 'id': ident}, {'action': 'stop', 'id': '--all'}, {'action': 'stop', 'id': 'b' * 64}, {'action': 'stop', 'kind': 'project', 'id': 'other'}):
                with self.assertRaises(ValueError): self.panel.action(value)
            job = self.panel.action({'action': 'restart', 'kind': 'project', 'id': 'demo;echo bad'})
            self.assertEqual(worker.call_args.kwargs['args'][1], [ident])
            self.assertEqual(self.panel.job(job['id'])['status'], 'running')
            with self.assertRaises(ValueError): self.panel.action({'action': 'stop', 'id': ident})
        with self.assertRaises(ValueError): self.panel.job('../file')

    def test_logs_validate_shell_input_and_bound_output(self):
        for ident, tail in (('--help', '200'), ('a' * 12 + ';id', '200'), ('a' * 12, '0'), ('a' * 12, '1001'), ('a' * 12, '2;id')):
            with self.assertRaises(ValueError): self.panel.logs(ident, tail)
        with patch.object(dashboard, 'Kit', return_value=self.kit), patch.object(dashboard.subprocess, 'run', return_value=SimpleNamespace(stdout=b'x' * (dashboard.LOG_LIMIT + 1))) as run:
            data = self.panel.logs('a' * 64, '200')
            self.assertTrue(data['truncated']); self.assertEqual(len(data['text']), dashboard.LOG_LIMIT)
            self.assertNotIn('--follow', run.call_args.args[0][-1])
