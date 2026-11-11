import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot import Job, State, classify, embed, job_key, display_date, canonical_url, extract_term, is_us_location, run_cycle, ML_BASELINE_VERSION


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

    def test_pure_machine_learning_is_excluded(self):
        for title in (
            "Machine Learning Engineer Intern", "AI/ML Research Intern",
            "Deep Learning Intern", "Computer Vision Intern",
            "Generative AI Intern", "Applied Scientist Intern",
            "NLP Intern", "MLOps Intern",
        ):
            with self.subTest(title=title):
                label = classify(Job("Test", "ai", "X", title, "Austin, TX", "https://example.com/ml"))
                self.assertIsNone(label)

    def test_embedded_ai_intern(self):
        for title in (
            "Embedded AI Intern", "Embedded ML Co-op", "TinyML Intern",
            "Edge AI Engineering Intern", "AI Accelerator Design Intern",
            "On-device Inference Intern", "Machine Learning Firmware Intern",
            "FPGA Machine Learning Intern",
        ):
            with self.subTest(title=title):
                label = classify(Job("Test", "edge", "X", title, "Remote - US", "https://example.com/edge"))
                self.assertIsNotNone(label)
                self.assertEqual(label[0], "Embedded AI / Edge ML")

    def test_ml_requires_device_side_scope(self):
        pure = Job("Test", "ml", "X", "Machine Learning Intern", "Austin, TX",
                   "https://example.com/ml", description="Build LLMs, recommendation systems, and data pipelines")
        self.assertIsNone(classify(pure))
        hybrid = Job("Test", "edge", "X", "Machine Learning Intern", "Austin, TX",
                     "https://example.com/edge",
                     description="Deploy optimized inference models on microcontrollers using TensorFlow Lite Micro.")
        self.assertEqual(classify(hybrid)[0], "Embedded AI / Edge ML")

    def test_new_ml_categories_baseline_but_do_not_suppress_existing_categories(self):
        state = State(":memory:")
        state.initialize("Simplify 2027")
        ml_job = Job("Simplify", "m1", "ML Co", "Embedded AI Intern", "Boston, MA", "https://example.com/ml1")
        hardware_job = Job("Simplify", "h1", "HW Co", "RTL Design Intern", "Boston, MA", "https://example.com/hw1")
        with patch("bot.sources", return_value=[("Simplify 2027", lambda: iter([ml_job, hardware_job]))]), \
             patch("bot.discord_send") as send:
            count = run_cycle({"location_scope": "US"}, state, object())
        self.assertEqual(count, 1)
        self.assertEqual(send.call_count, 1)
        self.assertTrue(state.is_seen(job_key(ml_job)))
        self.assertTrue(state.is_initialized(f"category-baseline:{ML_BASELINE_VERSION}:Simplify 2027"))
        new_ml = Job("Simplify", "m2", "ML Co", "Embedded AI Intern", "Boston, MA", "https://example.com/ml2")
        with patch("bot.sources", return_value=[("Simplify 2027", lambda: iter([ml_job, new_ml]))]), \
             patch("bot.discord_send") as send:
            count = run_cycle({"location_scope": "US"}, state, object())
        self.assertEqual(count, 1)
        self.assertEqual(send.call_count, 1)
        self.assertTrue(state.is_seen(job_key(new_ml))

    def test_non_intern_ai_excluded(self):
        self.assertIsNone(classify(Job("Test", "x", "X", "Senior Machine Learning Engineer", "CA", "https://example.com/x")))

    def test_invalid_date_unknown(self):
        self.assertEqual(display_date("unknown"), "Not provided")


if __name__ == "__main__":
    unittest.main()
