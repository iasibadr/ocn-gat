from dataclasses import replace
import unittest
from ocn_core.temporal_evidence import from_source,select_at

D1='2026-10-01T12:00:00+00:00';D2='2026-10-02T12:00:00+00:00';D3='2026-10-03T12:00:00+00:00'

class TemporalEvidenceTests(unittest.TestCase):
    def statement(self,value='drawer',observed=D1,effective=D1,source='note'):
        text='The shoes are in the '+value+'.'
        return from_source(text,subject='shoes',predicate='location',value=value,
            observed_at=observed,effective_at=effective,source_id=source,quote=text)

    def query(self,items,known=D3,effective=D3,**kw):
        args=dict(subject='shoes',predicate='location',known_at=known,effective_at=effective)
        args.update(kw);return select_at(items,**args)

    def test_current_update_preserves_historical_answer(self):
        old=self.statement();new=self.statement('locker',D2,D2,'update')
        items=[new,old];snapshot=list(items)
        self.assertEqual(self.query(items)['value'],'locker')
        self.assertEqual(self.query(items,effective=D1)['value'],'drawer')
        self.assertEqual(items,snapshot)
        self.assertFalse(self.query(items)['semantic_verification'])

    def test_late_arrival_cannot_rewrite_what_agent_knew(self):
        late=self.statement('locker',D3,D2,'late')
        old=self.statement()
        self.assertEqual(self.query([old,late],known=D2)['value'],'drawer')
        self.assertEqual(self.query([old,late])['value'],'locker')
        self.assertEqual(self.query([late],known=D2)['status'],'missing')

    def test_conflicting_latest_statements_do_not_use_arrival_order(self):
        self.assertEqual(self.query([self.statement(observed='2026-10-01T12:00:00Z')])['value'],'drawer')
        a=self.statement('locker',D2,D2,'a');b=self.statement('hall',D3,D2,'b')
        self.assertEqual(self.query([a,b]),self.query([b,a]))
        self.assertEqual(self.query([a,b])['status'],'conflict')
        self.assertIsNone(self.query([a,b])['value'])

    def test_unknown_time_is_not_invented_and_irrelevant_claims_do_not_block(self):
        unknown=self.statement('locker',D2,None)
        self.assertEqual(self.query([self.statement(),unknown])['status'],'unresolved_time')
        self.assertEqual(self.query([replace(unknown,subject='hat'),self.statement()])['value'],'drawer')
        future=self.statement('locker',D3,None)
        self.assertEqual(self.query([self.statement(),future],known=D2)['value'],'drawer')

    def test_literal_anchoring_and_zoned_time(self):
        with self.assertRaises(ValueError):from_source('Monday',subject='s',predicate='p',value='Friday',
            observed_at=D1,effective_at=D1,source_id='s',quote='Friday')
        with self.assertRaises(ValueError):self.statement(observed='2026-10-01T12:00:00')
        self.assertEqual(self.query([self.statement(observed='2026-10-01T12:00:00Z')])['value'],'drawer')
        a=self.statement('locker',D2,D2,'a')
        b=self.statement('hall',D3,'2026-10-02T14:00:00+02:00','b')
        self.assertEqual(self.query([a,b])['status'],'conflict')
        with self.assertRaises(ValueError):self.query([a]*257)

    def test_future_effective_statement_is_not_current_state(self):
        future=self.statement('locker',D1,D3,'future')
        self.assertEqual(self.query([self.statement(),future],known=D2,effective=D2)['value'],'drawer')
        corroboration=self.statement('drawer',D2,D1,'second-source')
        result=self.query([self.statement(),corroboration])
        self.assertEqual(result['value'],'drawer');self.assertEqual(len(result['evidence']),2)

if __name__=='__main__':unittest.main()
