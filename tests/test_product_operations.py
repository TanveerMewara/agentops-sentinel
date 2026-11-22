import unittest

from pydantic import ValidationError

from sentinel.product_operations import LabCampaignComplete
from sentinel.sessions import InvitationAccept, LoginCreate, _password


class ProductOperationsTests(unittest.TestCase):
    def test_password_hash_is_salted_deterministic_and_not_plaintext(self):
        first=_password('StrongPassword123','00'*16)
        self.assertEqual(first,_password('StrongPassword123','00'*16))
        self.assertNotEqual(first,_password('StrongPassword123','11'*16))
        self.assertNotIn('StrongPassword',first)

    def test_invitation_and_login_inputs_are_bounded(self):
        InvitationAccept(token='x'*32,display_name='Member Name',password='StrongPassword123')
        LoginCreate(organization_slug='sample-org',handle='member.one',password='x')
        for password in ('short','aaaaaaaaaaaa','123456789012'):
            with self.assertRaises(ValidationError):
                InvitationAccept(token='x'*32,display_name='Member Name',password=password)

    def test_lab_verdict_must_match_bounded_counts(self):
        LabCampaignComplete(passed=True,checks_run=10,checks_failed=0,duration_ms=1)
        for value in ({'passed':True,'checks_run':10,'checks_failed':1,'duration_ms':1},
                      {'passed':False,'checks_run':10,'checks_failed':0,'duration_ms':1},
                      {'passed':False,'checks_run':1,'checks_failed':2,'duration_ms':1}):
            with self.assertRaises(ValidationError): LabCampaignComplete(**value)


if __name__=='__main__': unittest.main()
