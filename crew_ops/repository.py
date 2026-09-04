"""Read-only access to the Crew Ops Advisor JSON dataset."""

from __future__ import annotations

import json
from datetime import date as Date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


class DatasetRepository:
    """Load and query the dataset without exposing file-system access to the LLM."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = data_dir or Path(__file__).resolve().parent.parent / "data"
        if not self.data_dir.is_dir():
            raise FileNotFoundError(f"Dataset directory not found: {self.data_dir}")

    @lru_cache(maxsize=None)
    def _load(self, filename: str) -> Any:
        path = self.data_dir / filename
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _matches(value: str, requested: str) -> bool:
        return not requested or value.casefold() == requested.casefold()

    def get_crew(self, crew_id: str) -> Optional[Dict[str, Any]]:
        return next((item for item in self._load("crew.json") if item["crew_id"] == crew_id), None)

    def search_crew(
        self,
        rank: str = "",
        base: str = "",
        status: str = "",
        aircraft_rating: str = "",
    ) -> List[Dict[str, Any]]:
        results = []
        for item in self._load("crew.json"):
            if not self._matches(item["rank"], rank):
                continue
            if not self._matches(item["base"], base):
                continue
            if not self._matches(item["status"], status):
                continue
            if aircraft_rating and aircraft_rating.casefold() not in {
                rating.casefold() for rating in item["ratings"]
            }:
                continue
            results.append(item)
        return results

    def get_flight(self, flight_id: str) -> Optional[Dict[str, Any]]:
        return next((item for item in self._load("flights.json") if item["flight_id"] == flight_id), None)

    def search_flights(
        self,
        date: str = "",
        departure_station: str = "",
        arrival_station: str = "",
        flight_no: str = "",
    ) -> List[Dict[str, Any]]:
        results = []
        for item in self._load("flights.json"):
            if date and item["date"] != date:
                continue
            if not self._matches(item["dep_station"], departure_station):
                continue
            if not self._matches(item["arr_station"], arrival_station):
                continue
            if not self._matches(item["flight_no"], flight_no):
                continue
            results.append(item)
        return results

    def count_flights(
        self,
        date: str = "",
        departure_station: str = "",
        arrival_station: str = "",
        flight_no: str = "",
    ) -> Dict[str, Any]:
        """Count flight legs matching the same filters used by search_flights."""
        matches = self.search_flights(date, departure_station, arrival_station, flight_no)
        return {
            "count": len(matches),
            "filters": {
                "date": date or None,
                "departure_station": departure_station or None,
                "arrival_station": arrival_station or None,
                "flight_no": flight_no or None,
            },
        }

    def search_station_window(
        self,
        date: str,
        station: str,
        window_start_utc: str,
        window_end_utc: str,
    ) -> Dict[str, Any]:
        """Find flights arriving at or departing from a station inside a UTC window."""
        Date.fromisoformat(date)

        def parse_window_time(value: str) -> datetime:
            normalized = value.removesuffix("Z")
            if "T" not in normalized:
                normalized = f"{date}T{normalized}"
            return datetime.fromisoformat(normalized)

        start = parse_window_time(window_start_utc)
        end = parse_window_time(window_end_utc)
        if start > end:
            raise ValueError("window_start_utc must be on or before window_end_utc")

        station_code = station.upper()
        matches = []
        for flight in self.search_flights(date=date):
            departure = datetime.fromisoformat(flight["dep_utc"].removesuffix("Z"))
            arrival = datetime.fromisoformat(flight["arr_utc"].removesuffix("Z"))
            affected_events = []
            if flight["dep_station"].upper() == station_code and start <= departure <= end:
                affected_events.append("departure")
            if flight["arr_station"].upper() == station_code and start <= arrival <= end:
                affected_events.append("arrival")
            if affected_events:
                matches.append({**flight, "affected_events": affected_events})

        return {
            "station": station_code,
            "window_start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(matches),
            "flights": matches,
        }

    def get_pairing(self, pairing_id: str) -> Optional[Dict[str, Any]]:
        pairings = self._load("rosters.json")["pairings"]
        return next((item for item in pairings if item["pairing_id"] == pairing_id), None)

    def get_crew_roster(self, crew_id: str) -> List[Dict[str, Any]]:
        matches = []
        for pairing in self._load("rosters.json")["pairings"]:
            member = next((member for member in pairing["crew"] if member["crew_id"] == crew_id), None)
            if member:
                matches.append({
                    "pairing_id": pairing["pairing_id"],
                    "role": member["role"],
                    "days": pairing["days"],
                })
        return matches

    def get_flagged_exceptions(self) -> List[Dict[str, Any]]:
        return self._load("rosters.json")["flagged_exceptions"]

    def get_reserves(self, date: str = "", base: str = "", rank: str = "") -> List[Dict[str, Any]]:
        crew_by_id = {item["crew_id"]: item for item in self._load("crew.json")}
        results = []
        for reserve in self._load("reserve_pool.json"):
            crew = crew_by_id[reserve["crew_id"]]
            if date and date not in reserve["dates"]:
                continue
            if not self._matches(reserve["base"], base):
                continue
            if not self._matches(crew["rank"], rank):
                continue
            results.append({**reserve, "crew": crew})
        return results

    def assess_reserves_for_aircraft_duty(
        self,
        date: str,
        aircraft: str,
        rank: str,
        notification_time_utc: str = "",
    ) -> Dict[str, Any]:
        """Assess reserves against a duty report derived from an aircraft's first flight."""
        duty_date = Date.fromisoformat(date)
        flights = [
            flight
            for flight in self._load("flights.json")
            if flight["date"] == date and flight["aircraft"].casefold() == aircraft.casefold()
        ]
        if not flights:
            raise ValueError(f"No flights found for aircraft {aircraft} on {date}")
        flights.sort(key=lambda flight: flight["dep_utc"])
        first_flight = flights[0]
        first_departure = datetime.fromisoformat(first_flight["dep_utc"].removesuffix("Z"))
        required_report = first_departure - timedelta(minutes=60)
        duty_base = first_flight["dep_station"]
        aircraft_type = first_flight["aircraft_type"]

        crew_by_id = {item["crew_id"]: item for item in self._load("crew.json")}
        certifications = self._load("certifications.json")
        candidates = []
        for reserve in self._load("reserve_pool.json"):
            crew = crew_by_id[reserve["crew_id"]]
            if not self._matches(crew["rank"], rank):
                continue

            window = reserve["oncall_window_utc"]
            window_start = datetime.fromisoformat(f"{date}T{window['start']}:00")
            window_end = datetime.fromisoformat(f"{date}T{window['end']}:00")
            report_in_window = window_start <= required_report <= window_end
            available_on_date = date in reserve["dates"]
            own_base = reserve["base"].casefold() == duty_base.casefold()
            correct_rating = aircraft_type.casefold() in {
                rating.casefold() for rating in crew["ratings"]
            }
            active = crew["status"] == "active"
            crew_certs = [item for item in certifications if item["crew_id"] == crew["crew_id"]]
            invalid_certs = [
                item["cert_type"]
                for item in crew_certs
                # The supplied validator and answer keys define validity by expiry date.
                if Date.fromisoformat(item["valid_to"]) < duty_date
            ]

            checks = {
                "available_on_date": available_on_date,
                "active": active,
                "own_base": own_base,
                "required_report_in_oncall_window": report_in_window,
                "correct_aircraft_rating": correct_rating,
                "all_certifications_valid": not invalid_certs,
            }
            reasons = []
            if not available_on_date:
                reasons.append(f"not in reserve pool on {date}")
            if not active:
                reasons.append(f"crew status is {crew['status']}")
            if not own_base:
                reasons.append(f"based at {reserve['base']}; duty starts at {duty_base}")
            if not report_in_window:
                reasons.append(
                    f"on-call window {window['start']}-{window['end']}Z does not cover "
                    f"required report {required_report.strftime('%H:%M')}Z"
                )
            if not correct_rating:
                reasons.append(f"RULE-QUAL-05: no {aircraft_type} rating")
            if invalid_certs:
                reasons.append(f"RULE-CERT-06: invalid certifications: {', '.join(invalid_certs)}")

            candidates.append(
                {
                    "crew_id": crew["crew_id"],
                    "name": crew["name"],
                    "base": reserve["base"],
                    "ratings": crew["ratings"],
                    "oncall_window_utc": window,
                    "checks": checks,
                    "eligible": all(checks.values()),
                    "reasons": reasons,
                }
            )

        candidates.sort(key=lambda item: (not item["eligible"], item["crew_id"]))
        return {
            "date": date,
            "aircraft": first_flight["aircraft"],
            "aircraft_type": aircraft_type,
            "duty_base": duty_base,
            "first_flight_id": first_flight["flight_id"],
            "first_departure_utc": first_flight["dep_utc"],
            "required_report_utc": required_report.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "notification_time_utc": notification_time_utc or None,
            "window_rule": "The required report time, not notification time, must be inside the reserve window.",
            "eligible_crew_ids": [item["crew_id"] for item in candidates if item["eligible"]],
            "candidates": candidates,
        }

    def get_duty_clock(self, crew_id: str) -> Optional[Dict[str, Any]]:
        return next(
            (item for item in self._load("duty_clocks.json") if item["crew_id"] == crew_id),
            None,
        )

    def search_crew_by_rolling_duty(
        self,
        end_date: str,
        minimum_hours: float,
        window_days: int = 7,
        include_planned_duty: bool = True,
    ) -> Dict[str, Any]:
        """Calculate rolling duty hours from daily history plus rostered plans."""
        if window_days < 1:
            raise ValueError("window_days must be at least 1")
        end = Date.fromisoformat(end_date)
        start = end.fromordinal(end.toordinal() - window_days + 1)

        totals: Dict[str, Dict[str, float]] = {}
        for clock in self._load("duty_clocks.json"):
            history_hours = sum(
                float(day["duty_hours"])
                for day in clock["daily_history"]
                if start <= Date.fromisoformat(day["date"]) <= end
            )
            totals[clock["crew_id"]] = {
                "history_hours": history_hours,
                "planned_hours": 0.0,
            }

        if include_planned_duty:
            for pairing in self._load("rosters.json")["pairings"]:
                for day in pairing["days"]:
                    duty_date = Date.fromisoformat(day["date"])
                    if not start <= duty_date <= end:
                        continue
                    report = datetime.fromisoformat(day["report_utc"].removesuffix("Z"))
                    release = datetime.fromisoformat(day["release_utc"].removesuffix("Z"))
                    duty_hours = (release - report).total_seconds() / 3600
                    for member in pairing["crew"]:
                        totals[member["crew_id"]]["planned_hours"] += duty_hours

        matches = []
        for crew_id, hours in totals.items():
            total_hours = round(hours["history_hours"] + hours["planned_hours"], 2)
            if total_hours >= minimum_hours:
                matches.append(
                    {
                        "crew_id": crew_id,
                        "history_duty_hours": round(hours["history_hours"], 2),
                        "planned_duty_hours": round(hours["planned_hours"], 2),
                        "total_duty_hours": total_hours,
                    }
                )
        matches.sort(key=lambda item: (-item["total_duty_hours"], item["crew_id"]))
        return {
            "window_start_date": start.isoformat(),
            "window_end_date": end.isoformat(),
            "window_days": window_days,
            "include_planned_duty": include_planned_duty,
            "minimum_hours": minimum_hours,
            "count": len(matches),
            "crew": matches,
        }

    def get_certifications(self, crew_id: str) -> List[Dict[str, Any]]:
        return [item for item in self._load("certifications.json") if item["crew_id"] == crew_id]

    def search_certifications(
        self,
        valid_to_from: str = "",
        valid_to_through: str = "",
        cert_type: str = "",
        crew_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Search certificates using inclusive ISO-date boundaries."""
        start = Date.fromisoformat(valid_to_from) if valid_to_from else None
        end = Date.fromisoformat(valid_to_through) if valid_to_through else None
        if start and end and start > end:
            raise ValueError("valid_to_from must be on or before valid_to_through")

        results = []
        for item in self._load("certifications.json"):
            expires = Date.fromisoformat(item["valid_to"])
            if start and expires < start:
                continue
            if end and expires > end:
                continue
            if not self._matches(item["cert_type"], cert_type):
                continue
            if not self._matches(item["crew_id"], crew_id):
                continue
            results.append(item)
        return sorted(results, key=lambda item: (item["valid_to"], item["crew_id"], item["cert_type"]))

    def get_risk_signal(self, crew_id: str) -> Optional[Dict[str, Any]]:
        return next(
            (item for item in self._load("risk_signals.json") if item["crew_id"] == crew_id),
            None,
        )

    def get_rules(self, rule_id: str = "") -> Dict[str, Any]:
        rules = self._load("rules.json")
        if not rule_id:
            return rules
        rule = next((item for item in rules["rules"] if item["rule_id"] == rule_id), None)
        return {
            "time_convention": rules["time_convention"],
            "definitions": rules["definitions"],
            "rule": rule,
        }

    def get_costs(self) -> Dict[str, Any]:
        return self._load("costs.json")

    def list_scenarios(self) -> List[Dict[str, Any]]:
        return [
            {
                "scenario_id": item["scenario_id"],
                "difficulty": item["difficulty"],
                "title": item["title"],
            }
            for item in self._load("scenarios.json")
        ]

    def get_scenario(self, scenario_id: str, include_answer_key: bool = False) -> Optional[Dict[str, Any]]:
        scenario = next(
            (item for item in self._load("scenarios.json") if item["scenario_id"] == scenario_id),
            None,
        )
        if scenario is None or include_answer_key:
            return scenario
        return {key: value for key, value in scenario.items() if key != "answer_key"}

    def get_question(self, question_id: str, include_expected_answer: bool = False) -> Optional[Dict[str, Any]]:
        question = next(
            (item for item in self._load("questions.json") if item["question_id"] == question_id),
            None,
        )
        if question is None or include_expected_answer:
            return question
        return {
            key: value
            for key, value in question.items()
            if key not in {"expected_answer", "explanation"}
        }
