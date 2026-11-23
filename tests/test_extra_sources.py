import unittest
from unittest.mock import patch
from requests import Session
from bot import Job, State, sources, run_cycle, job_key
from extra_sources import (
    _workday_board, hardware_internships_jobs, applyguy_jobs,
    workable_jobs, workday_jobs,
)


class FakeResponse:
    status_code = 200

    def __init__(self, *, text="", json_data=None):
        self.text = text
        self.data = json_data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class SourceTests(unittest.TestCase):
    def test_hardware_table_excludes_newgrad(self):
        body = (
            "<!-- INTERNSHIPS:START -->\n"
            "| Company | Role | Location | Posted | Link |\n"
            "| ACME | Embedded Firmware Intern | Seattle, WA | 2026-11-22 | "
            "[Apply](https://example.com/abc) |\n"
            "<!-- INTERNSHIPS:END -->\n"
            "| ACME | Senior Hardware Engineer | Seattle, WA | 2026-11-22 | "
            "[Apply](https://example.com/def) |"
        )
        with patch("extra_sources._get", return_value=FakeResponse(text=body)):
            jobs = list(hardware_internships_jobs(Session(), Job))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Embedded Firmware Intern")

    def test_applyguy_direct_url(self):
        data = {"jobs": [{
            "id": "abc", "company": "ACME", "title": "Firmware Engineer Intern",
            "location": "Seattle, WA", "posted": "2026-11-20",
            "listingUrl": "https://jobs.example.com/firmware",
            "url": "https://applyguy.ai/jobs?id=abc",
        }]}
        with patch("extra_sources._get", return_value=FakeResponse(json_data=data)):
            jobs = list(applyguy_jobs(Session(), Job))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].url, "https://jobs.example.com/firmware")

    def test_workable_widget(self):
        data = {"jobs": [{
            "title": "Hardware Engineer Intern",
            "shortcode": "AB123",
            "location": {"city": "Boston", "state": "MA", "country": "US"},
        }]}
        with patch("extra_sources._get", return_value=FakeResponse(json_data=data)):
            jobs = list(workable_jobs(Session(), "ACME", "acme", Job))
        self.assertEqual(len(jobs), 1)
        self.assertIn("Boston", jobs[0].location)

    def test_workday_board_parsing(self):
        self.assertEqual(
            _workday_board("https://marvell.wd1.myworkdayjobs.com/en-US/marvellcareers"),
            ("marvell.wd1.myworkdayjobs.com", "marvell", "marvellcareers"),
        )
        with self.assertRaises(ValueError):
            _workday_board("https://notworkday.com/jobs")

    def test_workday_limited_search(self):
        data = {"jobPostings": [{
            "title": "Firmware Engineer Intern",
            "externalPath": "/job/Seattle/Firmware-Intern_REQ-7",
            "locationsText": "Seattle, WA",
        }]}
        session = unittest.mock.Mock()
        session.post.return_value = FakeResponse(json_data=data)
        with patch("extra_sources._get", return_value=FakeResponse(
            json_data={"jobPostingInfo": {
                "jobDescription": "Firmware development using C",
                "location": "Seattle, WA", "country": {"descriptor": "United States"}
            }}
        )):
            jobs = list(workday_jobs(
                session, "ACME", "https://acme.wd1.myworkdayjobs.com/careers", Job,
            ))
        self.assertEqual(len(jobs), 1)
        self.assertIn("/careers/job/", jobs[0].url)
        self.assertIn("United States", jobs[0].location)
        self.assertEqual(session.post.call_count, 6)

    def test_new_sources_are_available(self):
        names = [name for name, _ in sources({
            "simplify_2027": True, "hardware_2027": True, "applyguy_2027": True,
            "greenhouse": {"ACME": "acme"}, "lever": {"B": "b"},
            "ashby": {"C": "c"}, "workable": {"D": "d"},
            "workday": {"E": "https://e.wd1.myworkdayjobs.com/careers"},
        }, Session())]
        self.assertEqual(len(names), 8)

    def test_poll_cadence_persists_in_state(self):
        state = State(":memory:")
        self.assertTrue(state.due("Greenhouse:acme", 120))
        state.note_polled("Greenhouse:acme")
        self.assertFalse(state.due("Greenhouse:acme", 120))
        self.assertTrue(state.due("Greenhouse:acme", 0))


if __name__ == "__main__":
    unittest.main()
