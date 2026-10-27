import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot import Job, State, classify, embed, job_key, display_date, canonical_url, extract_term, is_us_location


class BotTests(unittest.TestCase):
    def test_sample_format(self):
        job = Job("Simplify", "a", "GlobalFoundries", "Silicon Photonics Reliability Engineering Intern",
                  "Malta, NY", "https://example.com/1", "2026-09-28", "Summer 2027")
        label = classify(job)
        self.assertIsNotNone(label)
        self.assertEqual(label[0], "Semiconductor / Silicon")
        result = embed(job, label)
        self.assertEqual(result["fields"][2]["value"], "Sep 28, 2026")
        self.assertEqual(result["fields"][3]["value"], "Summer 2027")
        self.assertIn("silicon", result["fields"][4]["value"].lower())

    def test_embedded_coop(self):
        self.assertEqual(classify(Job("Test", "2", "X", "Embedded Firmware Co-op", "Remote", "https://example.com/2"))[0], "Embedded / Firmware")

    def test_digital_rtl(self):
        self.assertEqual(classify(Job("Test", "2", "X", "RTL Design Verification Intern", "CA", "https://example.com/3"))[0], "RTL / ASIC / FPGA")

    def test_generic_software_excluded(self):
        self.assertIsNone(classify(Job("Test", "2", "X", "Full Stack Software Intern", "Remote", "https://example.com/2")))

    def test_not_a_full_time_job(self):
        self.assertIsNone(classify(Job("Test", "2", "X", "Senior FPGA Engineer", "Remote", "https://example.com/2")))

    def test_description_specific_roles(self):
        job = Job("Test", "2", "X", "Software Engineer Intern", "Remote", "https://example.com/2",
                  description="Develop firmware for an embedded microcontroller using RTOS.")
        self.assertIsNotNone(classify(job))

    def test_canonical_url_and_state(self):
        a = Job("Simplify", "12", "X", "FPGA Intern", "TX", "https://job-boards.greenhouse.io/foo/jobs/123?utm_source=Simplify")
        b = Job("Greenhouse", "123", "X", "FPGA Intern", "TX", "https://job-boards.greenhouse.io/foo/jobs/123")
        self.assertEqual(job_key(a), job_key(b))
        state = State(":memory:")
        self.assertFalse(state.is_seen(job_key(a)))
        state.mark(job_key(a))
        self.assertTrue(state.is_seen(job_key(b)))
        self.assertFalse(state.is_initialized("Simplify"))
        state.initialize("Simplify")
        self.assertTrue(state.is_initialized("Simplify"))

    def test_term(self):
        self.assertEqual(extract_term("Summer 2027 / Fall 2027 Hardware Intern"), "Summer 2027, Fall 2027")

    def test_us_location_filter(self):
        self.assertTrue(is_us_location("Malta, NY"))
        self.assertTrue(is_us_location("Austin, TX"))
        self.assertTrue(is_us_location("Remote - United States"))
        self.assertTrue(is_us_location("San Francisco, California"))
        self.assertTrue(is_us_location("SF"))
        self.assertTrue(is_us_location("Toronto, ON, Canada / Boston, MA"))
        self.assertFalse(is_us_location("Toronto, ON, Canada"))
        self.assertFalse(is_us_location("Vancouver, BC, Canada"))
        self.assertFalse(is_us_location("London, UK"))
        self.assertFalse(is_us_location("Remote"))
        self.assertFalse(is_us_location(""))

    def test_invalid_date_unknown(self):
        self.assertEqual(display_date("unknown"), "Not provided")


if __name__ == "__main__":
    unittest.main()
