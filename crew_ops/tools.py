"""Tools for the Crew Ops Advisor dataset."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


from crew_ops.repository import DatasetRepository


repo = DatasetRepository()

def get_crew(crew_id: str) -> Optional[Dict[str, Any]]:
    """Get one crew member by exact ID, for example C-1042."""
    return repo.get_crew(crew_id)



def search_crew(
    rank: str = "",
    base: str = "",
    status: str = "",
    aircraft_rating: str = "",
) -> List[Dict[str, Any]]:
    """Search crew using optional exact rank, base, status, and aircraft rating filters."""
    return repo.search_crew(rank, base, status, aircraft_rating)



def get_flight(flight_id: str) -> Optional[Dict[str, Any]]:
    """Get one flight leg by its date-specific flight ID."""
    return repo.get_flight(flight_id)



def search_flights(
    date: str = "",
    departure_station: str = "",
    arrival_station: str = "",
    flight_no: str = "",
) -> List[Dict[str, Any]]:
    """Search flight legs by date, stations, or recurring flight number."""
    return repo.search_flights(date, departure_station, arrival_station, flight_no)



def count_flights(
    date: str = "",
    departure_station: str = "",
    arrival_station: str = "",
    flight_no: str = "",
) -> Dict[str, Any]:
    """Count flight legs matching optional date, station, and flight-number filters."""
    return repo.count_flights(date, departure_station, arrival_station, flight_no)



def search_station_window(
    date: str,
    station: str,
    window_start_utc: str,
    window_end_utc: str,
) -> Dict[str, Any]:
    """Find flights arriving at or departing from a station inside an inclusive UTC time window. Use YYYY-MM-DD for date and HH:MM or full ISO timestamps for window values."""
    return repo.search_station_window(date, station, window_start_utc, window_end_utc)



def get_pairing(pairing_id: str) -> Optional[Dict[str, Any]]:
    """Get a pairing with its crew, duty days, report/release times, and flight IDs."""
    return repo.get_pairing(pairing_id)



def get_crew_roster(crew_id: str) -> List[Dict[str, Any]]:
    """Get every rostered pairing and duty day for a crew member."""
    return repo.get_crew_roster(crew_id)



def get_flagged_roster_exceptions() -> List[Dict[str, Any]]:
    """Get the deliberately flagged roster compliance exceptions."""
    return repo.get_flagged_exceptions()



def get_reserves(date: str = "", base: str = "", rank: str = "") -> List[Dict[str, Any]]:
    """Find reserve crew by optional date, base, and rank; includes their crew profile."""
    return repo.get_reserves(date, base, rank)



def assess_reserves_for_aircraft_duty(
    date: str,
    aircraft: str,
    rank: str,
    notification_time_utc: str = "",
) -> Dict[str, Any]:
    """Assess reserve crew for an aircraft duty. Derives first departure and required report, then checks reserve date/window, base, rank, rating, status, and certifications. Reserve window applies to required report, not notification time."""
    return repo.assess_reserves_for_aircraft_duty(date, aircraft, rank, notification_time_utc)



def get_duty_clock(crew_id: str) -> Optional[Dict[str, Any]]:
    """Get current rolling summaries, last rest, and daily duty history for one crew member."""
    return repo.get_duty_clock(crew_id)



def search_crew_by_rolling_duty(
    end_date: str,
    minimum_hours: float,
    window_days: int = 7,
    include_planned_duty: bool = True,
) -> Dict[str, Any]:
    """Find crew at or above a rolling duty-hour threshold. Uses an inclusive calendar-day window and can add rostered duty plans."""
    return repo.search_crew_by_rolling_duty(
        end_date,
        minimum_hours,
        window_days,
        include_planned_duty,
    )



def get_certifications(crew_id: str) -> List[Dict[str, Any]]:
    """Get all certification validity periods for one crew member."""
    return repo.get_certifications(crew_id)



def search_certifications(
    valid_to_from: str = "",
    valid_to_through: str = "",
    cert_type: str = "",
    crew_id: str = "",
) -> List[Dict[str, Any]]:
    """Search certifications by inclusive expiry-date range (YYYY-MM-DD), type, or crew ID."""
    return repo.search_certifications(valid_to_from, valid_to_through, cert_type, crew_id)



def get_risk_signal(crew_id: str) -> Optional[Dict[str, Any]]:
    """Get the supplied disruption-risk score and drivers for one crew member."""
    return repo.get_risk_signal(crew_id)



def get_rules(rule_id: str = "") -> Dict[str, Any]:
    """Get all operating rules, or one rule such as RULE-REST-04."""
    return repo.get_rules(rule_id)



def get_costs() -> Dict[str, Any]:
    """Get all recovery cost assumptions in INR."""
    return repo.get_costs()



def list_scenarios() -> List[Dict[str, Any]]:
    """List the public worked scenarios without their answer keys."""
    return repo.list_scenarios()



def get_scenario(scenario_id: str, include_answer_key: bool = False) -> Optional[Dict[str, Any]]:
    """Get a public scenario. Answer keys are excluded unless explicitly requested."""
    return repo.get_scenario(scenario_id, include_answer_key)



def get_question(question_id: str, include_expected_answer: bool = False) -> Optional[Dict[str, Any]]:
    """Get an evaluation question. Expected answers are excluded unless explicitly requested."""
    return repo.get_question(question_id, include_expected_answer)


toolbox = [
    get_crew,
    search_crew,
    get_flight,
    search_flights,
    count_flights,
    search_station_window,
    get_pairing,
    get_crew_roster,
    get_flagged_roster_exceptions,
    get_reserves,
    assess_reserves_for_aircraft_duty,
    get_duty_clock,
    search_crew_by_rolling_duty,
    get_certifications,
    search_certifications,
    get_risk_signal,
    get_rules,
    get_costs,
    list_scenarios,
    get_scenario,
    get_question
]

# if __name__ == "__main__":
#     run()
