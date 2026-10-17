import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ocn_core import gat
from ocn_core.agent_integration import Integration
from ocn_core.maintenance_policy import configure,status,tick,cycle_lock


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);docs=self.root/'docs';docs.mkdir();(docs/'a.md').write_text('Friday')
        self.instance=self.root/'instance';self.audit=self.root/'audit'
        gat.create(self.instance,docs,{'a':'a.md'},'When?',integration=Integration(b'def build_synthesizer(model): return None','build_synthesizer'),isolated=True)
        self.suite=dict(format='gat.acceptance-suite.v1',cases=[dict(id='one',question='When?',documents=[dict(document_id='a',text='Friday')],
            expected={'response':dict(answer='Friday',abstain=False,citations=[dict(document_id='a',quote='Friday')])})])
        configure(self.instance,'Contract',self.suite,'local-test',self.audit,2)

    @patch('ocn_core.maintenance_policy.hybrid_repair')
    def test_budget_persisted_before_work_and_not_reset(self,repair):
        def work(*args,**kwargs):
            self.assertGreater(status(self.instance)['used_cycles'],0)
            return {'status':'already_accepted','designer_calls':0}
        repair.side_effect=work
        tick(str(self.instance));tick(str(self.instance))
        with self.assertRaisesRegex(RuntimeError,'exhausted'):tick(str(self.instance))
        self.assertEqual(repair.call_count,2)
        with self.assertRaises(FileExistsError):configure(self.instance,'Contract',self.suite,'local-test',self.root/'new',2)
        self.assertEqual(status(self.instance)['remaining_cycles'],0)

    @patch('ocn_core.maintenance_policy.hybrid_repair',side_effect=TimeoutError('uncertain'))
    def test_failure_spends_cycle_without_retry(self,repair):
        with self.assertRaises(TimeoutError):tick(self.instance)
        self.assertEqual(status(self.instance)['used_cycles'],1);repair.assert_called_once()

    @patch('ocn_core.maintenance_policy.hybrid_repair')
    def test_pause_and_authority_change_prevent_work(self,repair):
        gat.set_paused(self.instance,True)
        with self.assertRaises(RuntimeError):tick(self.instance)
        gat.set_paused(self.instance,False)
        path=self.instance/'instance.json';config=json.loads(path.read_text());config['mission']='Changed';path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError,'authority'):tick(self.instance)
        self.assertEqual(status(self.instance)['used_cycles'],0);repair.assert_not_called()

    @patch('ocn_core.maintenance_policy.hybrid_repair')
    def test_concurrent_cycle_rejected_before_reservation(self,repair):
        with cycle_lock(self.instance):
            with self.assertRaisesRegex(RuntimeError,'already running'):tick(self.instance)
        repair.assert_not_called();self.assertEqual(status(self.instance)['used_cycles'],0)

    @patch('ocn_core.maintenance_policy.hybrid_repair')
    def test_bad_or_missing_policy_never_reinitialized(self,repair):
        p=self.instance/'maintenance.json';data=json.loads(p.read_text());data['used_cycles']=False;p.write_text(json.dumps(data))
        with self.assertRaises(ValueError):tick(self.instance)
        p.unlink()
        with self.assertRaises(OSError):tick(self.instance)
        repair.assert_not_called()

    @patch('ocn_core.maintenance_policy.hybrid_repair')
    def test_failed_reservation_prevents_work(self,repair):
        with patch('ocn_core.maintenance_policy.os.replace',side_effect=OSError('disk error')):
            with self.assertRaises(OSError):tick(self.instance)
        repair.assert_not_called();self.assertEqual(status(self.instance)['used_cycles'],0)

if __name__=='__main__':unittest.main()
