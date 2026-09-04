from pathlib import Path
import unittest

from crew_ops.repository import DatasetRepository


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class DatasetRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = DatasetRepository(DATA_DIR)

    def test_get_known_crew(self) -> None:
        crew = self.repo.get_crew("C-1042")
        self.assertIsNotNone(crew)
        self.assertEqual(crew["rank"], "Captain")
        self.assertIn("A320", crew["ratings"])

    def test_find_blr_reserve_captains(self) -> None:
        reserves = self.repo.get_reserves("2026-09-15", "BLR", "Captain")
        ids = {item["crew_id"] for item in reserves}
        self.assertIn("C-3310", ids)
        self.assertNotIn("C-2210", ids)

    def test_assess_atr_reserve_captains_uses_required_report(self) -> None:
        result = self.repo.assess_reserves_for_aircraft_duty(
            date="2026-09-16",
            aircraft="VT-DXE",
            rank="Captain",
            notification_time_utc="01:30Z",
        )
        self.assertEqual(result["aircraft_type"], "ATR72")
        self.assertEqual(result["required_report_utc"], "2026-09-16T03:00:00Z")
        self.assertEqual(result["eligible_crew_ids"], ["C-3315"])

        candidates = {item["crew_id"]: item for item in result["candidates"]}
        self.assertIn("RULE-QUAL-05: no ATR72 rating", candidates["C-3305"]["reasons"])
        self.assertIn(
            "on-call window 06:00-18:00Z does not cover required report 03:00Z",
            candidates["C-3310"]["reasons"],
        )

    def test_flight_search_uses_recurring_number(self) -> None:
        flights = self.repo.search_flights(date="2026-09-15", flight_no="DX401")
        self.assertEqual(len(flights), 1)
        self.assertEqual(flights[0]["flight_id"], "DX401-2026-09-15")

    def test_count_flights_for_date(self) -> None:
        result = self.repo.count_flights(date="2026-09-16")
        self.assertEqual(result["count"], 21)
        self.assertEqual(result["filters"]["date"], "2026-09-16")

    def test_search_station_closure_window(self) -> None:
        result = self.repo.search_station_window("2026-09-17", "BLR", "08:00", "14:00")
        self.assertEqual(result["count"], 13)
        self.assertEqual(
            [item["flight_id"] for item in result["flights"]],
            [
                "DX402-2026-09-17",
                "DX422-2026-09-17",
                "DX462-2026-09-17",
                "DX453-2026-09-17",
                "DX433-2026-09-17",
                "DX403-2026-09-17",
                "DX413-2026-09-17",
                "DX423-2026-09-17",
                "DX454-2026-09-17",
                "DX434-2026-09-17",
                "DX404-2026-09-17",
                "DX424-2026-09-17",
                "DX588-2026-09-17",
            ],
        )

    def test_scenario_hides_answer_by_default(self) -> None:
        scenario = self.repo.get_scenario("S2")
        self.assertIsNotNone(scenario)
        self.assertNotIn("answer_key", scenario)

    def test_search_certifications_by_expiry_window(self) -> None:
        certifications = self.repo.search_certifications("2026-09-15", "2026-10-15")
        self.assertEqual(
            [(item["crew_id"], item["cert_type"], item["valid_to"]) for item in certifications],
            [
                ("C-5417", "recurrent_training", "2026-09-17"),
                ("C-2087", "licence", "2026-09-18"),
                ("C-2091", "medical_class1", "2026-09-23"),
                ("C-3116", "dangerous_goods", "2026-09-28"),
                ("C-5020", "recurrent_training", "2026-10-03"),
                ("C-2993", "medical_class1", "2026-10-08"),
            ],
        )

    def test_search_rolling_duty_including_plan(self) -> None:
        result = self.repo.search_crew_by_rolling_duty(
            end_date="2026-09-15",
            minimum_hours=45,
            window_days=7,
            include_planned_duty=True,
        )
        self.assertEqual(result["window_start_date"], "2026-09-09")
        self.assertEqual(
            [(item["crew_id"], item["total_duty_hours"]) for item in result["crew"]],
            [("C-2087", 51.83), ("C-3305", 50.0)],
        )


if __name__ == "__main__":
    unittest.main()
