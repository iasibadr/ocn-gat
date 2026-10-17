import hashlib,json,unittest
from ocn_core.envelope_documents import EnvelopeDocuments

class Tests(unittest.TestCase):
    def setUp(self):
        self.text='Authorized content.';self.pins={'D':hashlib.sha256(self.text.encode()).hexdigest()}
    def adapter(self,remember=True):return EnvelopeDocuments(12345,self.pins,remember=remember)
    def raw(self,value):return json.dumps(value).encode()
    def test_new_shape_discovered_and_reused_without_calibration(self):
        a=self.adapter()
        for value in ({'text':self.text,'note':'x'},{'new':{'payload':[self.text]},'meta':'x'}):
            self.assertEqual(a.decode(self.raw(value),'D')[0],self.text)
            before=a.hash_checks
            a.decode(self.raw(value),'D')
            self.assertEqual(a.hash_checks-before,1)
        self.assertEqual(a.acquisitions,2);self.assertEqual(a.reuses,2)
    def test_classical_discovery_gets_same_values(self):
        a=self.adapter();b=self.adapter(False);raw=self.raw({'a':'wrong','b':self.text})
        for _ in range(3):self.assertEqual(a.decode(raw,'D'),b.decode(raw,'D'))
        self.assertLess(a.hash_checks,b.hash_checks)
    def test_same_shape_content_change_never_uses_stale_result(self):
        a=self.adapter();a.decode(self.raw({'a':self.text}),'D')
        with self.assertRaises(ValueError):a.decode(self.raw({'a':'replacement'}),'D')
    def test_same_shape_switches_valid_path(self):
        a=self.adapter();a.decode(self.raw({'a':self.text,'b':'other'}),'D')
        self.assertEqual(a.decode(self.raw({'a':'other','b':self.text}),'D')[1]['path'],['b'])
    def test_duplicate_contents_rejected_even_after_learning(self):
        a=self.adapter();a.decode(self.raw({'a':self.text,'b':'other'}),'D')
        with self.assertRaises(ValueError):a.decode(self.raw({'a':self.text,'b':self.text}),'D')
    def test_duplicate_keys_and_deep_envelopes_rejected(self):
        a=self.adapter()
        with self.assertRaises(ValueError):a.decode(b'{"x":1,"x":2}','D')
        value=self.text
        for _ in range(9):value={'x':value}
        with self.assertRaises(ValueError):a.decode(self.raw(value),'D')
    def test_method_transfers_to_another_authorized_document(self):
        other='Second authorized document.'
        a=EnvelopeDocuments(12345,{**self.pins,'E':hashlib.sha256(other.encode()).hexdigest()})
        a.decode(self.raw({'body':self.text,'meta':'first'}),'D')
        before=a.hash_checks
        result=a.decode(self.raw({'body':other,'meta':'second'}),'E')
        self.assertEqual(result[0],other)
        self.assertEqual(a.hash_checks-before,1)
        self.assertEqual(a.acquisitions,1)

    def test_methods_are_bounded(self):
        a=self.adapter()
        for i in range(12):a.decode(self.raw({str(i):self.text}),'D')
        self.assertEqual(len(a.methods),8)
if __name__=='__main__':unittest.main()
