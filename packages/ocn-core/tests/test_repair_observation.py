import unittest
from ocn_core.repair_observation import summarize


class ObservationTests(unittest.TestCase):
    def test_empty_response_is_explained_without_source_data(self):
        docs=[dict(document_id='private-id',text=''),dict(document_id='other',text='SECRET')]
        result=dict(status='completed',result=dict(response=dict(answer='',abstain=False,
            citations=[dict(document_id='private-id',quote='')]),usage={'secret':'SECRET'}))
        summary=summarize(docs,result)
        self.assertEqual(summary,dict(document_count=2,empty_document_count=1,violations=['empty_answer','empty_citation']))
        self.assertNotIn('private',str(summary));self.assertNotIn('SECRET',str(summary))

    def test_valid_abstention_has_no_structural_violation(self):
        r=dict(status='completed',result=dict(response=dict(answer='Absent',abstain=True,citations=[]),usage={}))
        self.assertEqual(summarize([],r)['violations'],[])

    def test_candidate_diagnostics_are_not_trusted(self):
        for result in (dict(status='failed',diagnostic='SECRET'),dict(status='completed',result={'violations':[]})):
            summary=summarize([],result)
            self.assertTrue(summary['violations']);self.assertNotIn('SECRET',str(summary))

    def test_forged_quote_is_reported_without_echo(self):
        r=dict(status='completed',result=dict(response=dict(answer='Monday',abstain=False,
            citations=[dict(document_id='x',quote='SECRET forged')]),usage={}))
        self.assertEqual(summarize([dict(document_id='x',text='Friday')],r)['violations'],['unsupported_citation'])

if __name__=='__main__':unittest.main()
