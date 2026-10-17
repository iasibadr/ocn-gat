import hashlib
import unittest
from ocn_core.evidence_revisions import Supersession,assess_revised_coverage

class RevisionTests(unittest.TestCase):
    def setUp(self):self.sources={'old':'yellow','new':'violet','third':'green'}
    def sha(self,s):return hashlib.sha256(self.sources[s].encode()).hexdigest()
    def edge(self,a='old',b='new',field='colour'):
        return Supersession(field,a,self.sha(a),b,self.sha(b))
    def rows(self,fields=('colour',),sources=('old','new')):
        return [dict(source_id=s,field=f,sha256=self.sha(s),status='value',value=self.sources[s],quote=self.sources[s]) for f in fields for s in sources]
    def assess(self,edges=(),rows=None,fields=('colour',),sources=('old','new')):
        return assess_revised_coverage(fields,{s:self.sources[s] for s in sources},self.rows(fields,sources) if rows is None else rows,host_supersessions=edges)
    def test_text_alone_cannot_grant_precedence(self):self.assertFalse(self.assess()['ready'])
    def test_pinned_revision_keeps_old_evidence(self):
        r=self.assess((self.edge(),));self.assertEqual(r['values'],{'colour':'violet'})
        self.assertFalse(r['original']['ready']);self.assertEqual(len(r['original']['fields']['colour']['observations']),2)
    def test_scope_is_per_field(self):
        r=self.assess((self.edge(),),fields=('colour','other'))
        self.assertTrue(r['fields']['colour']['ready']);self.assertFalse(r['fields']['other']['ready']);self.assertFalse(r['ready'])
    def test_replacement_absent_does_not_resurrect_old_value(self):
        rows=self.rows();rows[1].update(status='absent',value=None,quote=None)
        r=self.assess((self.edge(),),rows);self.assertFalse(r['ready'])
        self.assertIn('no_established_value',r['fields']['colour']['reasons'])
    def test_missing_replacement_blocks(self):
        r=self.assess((self.edge(),),self.rows()[:1]);self.assertFalse(r['ready'])
    def test_changed_fingerprint_invalidates_authority(self):
        e=self.edge();self.sources['new']='red'
        with self.assertRaisesRegex(ValueError,'version'):self.assess((e,))
    def test_cycle_rejected(self):
        with self.assertRaisesRegex(ValueError,'Cyclic'):self.assess((self.edge(),self.edge('new','old')))
    def test_transitive_replacements(self):
        r=self.assess((self.edge(),self.edge('new','third')),sources=('old','new','third'))
        self.assertEqual(r['values'],{'colour':'green'})
    def test_branches_do_not_choose_arbitrarily(self):
        r=self.assess((self.edge(),self.edge('old','third')),sources=('old','new','third'))
        self.assertFalse(r['ready']);self.assertIn('conflicting_values',r['fields']['colour']['reasons'])
    def test_invalid_old_observation_not_hidden(self):
        rows=self.rows();rows[0]['quote']='fabricated'
        with self.assertRaises(ValueError):self.assess((self.edge(),),rows)
    def test_duplicate_and_out_of_scope_rejected(self):
        for edges in ((self.edge(),self.edge()),(self.edge(field='unknown'),)):
            with self.assertRaises(ValueError):self.assess(edges)
    def test_order_invariance(self):
        edges=(self.edge(),self.edge('new','third'));names=('old','new','third')
        a=self.assess(edges,sources=names)
        b=self.assess(tuple(reversed(edges)),list(reversed(self.rows(sources=names))),sources=tuple(reversed(names)))
        self.assertEqual(a,b)
if __name__=='__main__':unittest.main()
