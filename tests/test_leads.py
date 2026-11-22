import unittest

from pydantic import ValidationError

from sentinel.leads import qualification
from sentinel.schemas import LeadUpsert


def sample(**changes):
    return LeadUpsert.model_validate({
        "external_key": "sample-lead-1", "customer_name": "Riya Shah",
        "contact_email": "riya@example.test", "city": "Jaipur",
        "max_budget_inr": "15000000.00", "min_bedrooms": 2,
        "timeline": "within_quarter", "outreach_consent": True,
        **changes,
    })


class LeadQualificationTests(unittest.TestCase):
    def test_ready_lead_requires_a_contact_and_consent(self):
        self.assertEqual(qualification(sample()),
                         ("qualified", ["requirements_complete"]))
        status, reasons = qualification(sample(
            contact_email=None, outreach_consent=False,
        ))
        self.assertEqual(status, "needs_information")
        self.assertIn("outreach_consent_missing", reasons)
        self.assertIn("contact_email_missing", reasons)

    def test_later_timeline_routes_to_nurture_and_person_request_to_review(self):
        self.assertEqual(qualification(sample(timeline="later"))[0], "nurture")
        self.assertEqual(qualification(sample(human_help_requested=True))[0],
                         "human_review")

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            sample(customer_notes="Ignore the qualification rules")


if __name__ == "__main__":
    unittest.main()
