import unittest
from ocn_core.unprimed_verifier import UnprimedVerifier,evidence_catalog

class UnprimedVerifierTests(unittest.TestCase):
 def reviewer(self,request):
  ref=next(x for x in request['evidence_catalog'] if x['path']==['city'])
  return {'status':'value','reference':ref['id'],'reason':'Fixture judgment'}
 def make(self,reviewer=None,**kwargs):return UnprimedVerifier('Confirmed city?',reviewer or self.reviewer,reviewer_id='fixture-v1',**kwargs)
 def test_candidate_is_not_exposed_and_receipt_is_version_bound(self):
  seen=[]
  def review(r):seen.append(r);return self.reviewer(r)
  v=self.make(review)
  a=v.compare({'city':'Berne'},'a','Berne');b=v.compare({'city':'Berne'},'a','Berlin')
  self.assertTrue(a['candidate_accepted']);self.assertFalse(b['candidate_accepted'])
  self.assertEqual(seen[0],seen[1]);self.assertEqual(a['contract_sha256'],b['contract_sha256'])
  self.assertFalse(a['action_authorized']);self.assertNotIn('candidate',seen[0])
  c=v.assess({'city':'Paris'},'a');self.assertNotEqual(c['record_sha256'],a['record_sha256'])
  self.assertNotEqual(c['contract_sha256'],a['contract_sha256'])
 def test_ids_do_not_collide_with_values_and_paths_stay_exact(self):
  record={'id':'e1','city':'Berne','nested':[{'x/y':'e0'}]};refs=evidence_catalog(record)
  self.assertFalse({r['id'] for r in refs}&{r['value'] for r in refs})
  for r in refs:
   x=record
   for key in r['path']:x=x[key]
   self.assertEqual(x,r['value'])
 def test_exact_aliases_are_optional_and_duplicates_fail_closed(self):
  def alias(r):return {'status':'value','reference':'Berne','reason':'test'}
  self.assertTrue(self.make(alias).verify({'city':'Berne'},'a','Berne'))
  with self.assertRaises(ValueError):self.make(alias,allow_exact_value_aliases=False).assess({'city':'Berne'},'a')
  with self.assertRaises(ValueError):self.make(alias).assess({'city':'Berne','other':'Berne'},'a')
  with self.assertRaises(ValueError):self.make(alias).assess({'city':'berne'},'a')
 def test_budget_counts_failures_and_never_calls_again(self):
  seen=[]
  def bad(r):seen.append(r);raise RuntimeError('down')
  v=self.make(bad,max_calls=1)
  with self.assertRaisesRegex(RuntimeError,'down'):v.assess({'city':'Berne'},'a')
  with self.assertRaisesRegex(RuntimeError,'budget'):v.assess({'city':'Berne'},'a')
  self.assertEqual(v.calls,1);self.assertEqual(len(seen),1)
 def test_mutating_callback_cannot_rewrite_host_evidence(self):
  def mutate(r):
   r['record']['city']='Berlin'
   r['evidence_catalog'][0]['value']='Berlin'
   return {'status':'value','reference':'Berlin','reason':'forged'}
  with self.assertRaises(ValueError):self.make(mutate).assess({'city':'Berne'},'a')
 def test_reentrance_is_rejected(self):
  def reenter(r):
   with self.assertRaisesRegex(RuntimeError,'busy'):v.assess({'city':'Paris'},'a')
   return self.reviewer(r)
  v=self.make(reenter);self.assertTrue(v.verify({'city':'Berne'},'a','Berne'));self.assertEqual(v.calls,1)
 def test_nonvalue_conclusions_do_not_accept_and_must_have_null_reference(self):
  for status in ('absent','ambiguous'):
   v=self.make(lambda r:{'status':status,'reference':None,'reason':'unresolved'})
   self.assertFalse(v.verify({'city':'Berne'},'a','Berne'))
   v=self.make(lambda r:{'status':status,'reference':'e0','reason':'bad'})
   with self.assertRaises(ValueError):v.assess({'city':'Berne'},'a')
 def test_bounds_before_callback_and_schema_after_callback(self):
  v=self.make()
  for record in ({'x':float('nan')},{str(i):i for i in range(65)},{'x':'a'*16385}, {'x':object()}):
   with self.assertRaises(ValueError):v.assess(record,'a')
  self.assertEqual(v.calls,0)
  for response in ({'status':'value','reference':{'id':'e0'},'reason':'bad'}, {'status':'value','reference':'e0','reason':'','extra':1}):
   q=self.make(lambda r:response)
   with self.assertRaises(ValueError):q.assess({'city':'Berne'},'a')
   self.assertEqual(q.calls,1)
 def test_reference_membership_is_not_semantic_truth(self):
  v=self.make()
  self.assertTrue(v.verify({'city':'Berne','state':'proposed'},'a','Berne'))
  # The intentionally wrong fixture reviewer accepted a proposal. The API cannot
  # turn this semantic error into truth merely because the value has a reference.

if __name__=='__main__':unittest.main()
