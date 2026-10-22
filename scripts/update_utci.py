from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


STATION_URL = "https://eodg.atm.ox.ac.uk/eodg/weather/weather.html"
LONDON = ZoneInfo("Europe/London")
HISTORY_LIMIT = 7
NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
TIMESTAMP_PATTERN = re.compile(r"\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2}\s+GMT")

MODEL_RANGES = {
    "air_temperature_c": (-50.0, 50.0),
    "mean_radiant_temperature_c": (-80.0, 120.0),
    "wind_speed_m_s": (0.5, 30.3),
    "relative_humidity_percent": (5.0, 100.0),
}


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    air_temperature_c: float
    relative_humidity_percent: float
    wind_speed_m_s: float


class StationPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.headings: list[str] = []
        self._row_cells: list[str] | None = None
        self._cell_text: list[str] | None = None
        self._heading_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row_cells = []
        elif tag == "td":
            self._cell_text = []
        elif tag == "h4":
            self._heading_text = []

    def handle_data(self, data: str) -> None:
        if self._cell_text is not None:
            self._cell_text.append(data)
        if self._heading_text is not None:
            self._heading_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell_text is not None:
            value = " ".join("".join(self._cell_text).split())
            if self._row_cells is not None:
                self._row_cells.append(value)
            self._cell_text = None
        elif tag == "tr" and self._row_cells is not None:
            self.rows.append(self._row_cells)
            self._row_cells = None
        elif tag == "h4" and self._heading_text is not None:
            self.headings.append(" ".join("".join(self._heading_text).split()))
            self._heading_text = None


def _first_number(value: str, label: str) -> float:
    match = NUMBER_PATTERN.search(value)
    if match is None:
        raise ValueError(f"Could not read {label} from the station page: {value!r}")
    number = float(match.group())
    if not math.isfinite(number) or number == -999:
        raise ValueError(f"The station returned a missing or invalid {label}: {value!r}")
    return number


def parse_station_page(page: str) -> Observation:
    parser = StationPageParser()
    parser.feed(page)

    values: dict[str, str] = {}
    for row in parser.rows:
        for index, label in enumerate(row[:-1]):
            if label.casefold() in {"temperature", "relative humidity", "wind"}:
                values[label.casefold()] = row[index + 1]
    required = ("temperature", "relative humidity", "wind")
    missing = [label for label in required if label not in values]
    if missing:
        raise ValueError(f"Station page is missing expected fields: {', '.join(missing)}")

    timestamp_text = next(
        (
            match.group()
            for heading in parser.headings
            if (match := TIMESTAMP_PATTERN.search(heading)) is not None
        ),
        None,
    )
    if timestamp_text is None:
        raise ValueError("Could not find the observation timestamp on the station page.")

    observed_at = datetime.strptime(
        timestamp_text, "%d-%m-%Y %H:%M:%S GMT"
    ).replace(tzinfo=timezone.utc)
    return Observation(
        observed_at=observed_at,
        air_temperature_c=_first_number(values["temperature"], "air temperature"),
        relative_humidity_percent=_first_number(
            values["relative humidity"], "relative humidity"
        ),
        wind_speed_m_s=_first_number(values["wind"], "wind speed"),
    )


def fetch_observation() -> Observation:
    request = Request(
        STATION_URL,
        headers={"User-Agent": "Oxford-NeuralUTCI/1.0 (weather observation display)"},
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        page = response.read().decode(charset)
    return parse_station_page(page)


def _clamp(value: float, limits: tuple[float, float]) -> float:
    return min(max(value, limits[0]), limits[1])


def model_inputs(observation: Observation) -> dict[str, float]:
    raw_inputs = {
        "air_temperature_c": observation.air_temperature_c,
        "mean_radiant_temperature_c": observation.air_temperature_c,
        "wind_speed_m_s": observation.wind_speed_m_s,
        "relative_humidity_percent": observation.relative_humidity_percent,
    }
    return {
        name: _clamp(value, MODEL_RANGES[name])
        for name, value in raw_inputs.items()
    }


def calculate_record(
    observation: Observation,
    calculated_at: datetime | None = None,
    model_function: Callable[..., float] | None = None,
    polynomial_function: Callable[..., object] | None = None,
) -> dict[str, object]:
    if model_function is None:
        from NeuralUTCI import utci

        model_function = utci
    if polynomial_function is None:
        from pythermalcomfort.models import utci

        polynomial_function = utci

    raw_inputs = {
        "air_temperature_c": observation.air_temperature_c,
        "mean_radiant_temperature_c": observation.air_temperature_c,
        "wind_speed_m_s": observation.wind_speed_m_s,
        "relative_humidity_percent": observation.relative_humidity_percent,
    }
    value = float(
        model_function(
            Ta=observation.air_temperature_c,
            Tr=observation.air_temperature_c,
            va=observation.wind_speed_m_s,
            rH=observation.relative_humidity_percent,
            oob="clamp",
        )
    )
    if not math.isfinite(value):
        raise ValueError("Neural-UTCI returned a non-finite UTCI value.")

    polynomial_value: float | None = None
    if 0.0 <= observation.relative_humidity_percent <= 100.0:
        polynomial_result = polynomial_function(
            tdb=observation.air_temperature_c,
            tr=observation.air_temperature_c,
            v=observation.wind_speed_m_s,
            rh=observation.relative_humidity_percent,
            units="SI",
            limit_inputs=True,
            round_output=False,
        )
        result_value = float(polynomial_result.utci)
        if math.isfinite(result_value):
            polynomial_value = round(result_value, 1)

    return {
        "observed_at": observation.observed_at.isoformat(),
        "calculated_at": (calculated_at or datetime.now(timezone.utc)).isoformat(),
        "utci_c": round(value, 1),
        "neural_utci_c": round(value, 1),
        "polynomial_utci_c": polynomial_value,
        "polynomial_status": (
            "calculated" if polynomial_value is not None else "outside_model_range"
        ),
        "inputs": raw_inputs,
        "model_inputs": model_inputs(observation),
    }


def _read_data(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"current": None, "history": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("history"), list):
        raise ValueError(f"Unexpected data format in {path}.")
    return data


def _write_data(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
    ) as temporary:
        json.dump(data, temporary, indent=2, ensure_ascii=False)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def update_data(
    path: Path,
    force: bool = False,
    now: datetime | None = None,
    observation: Observation | None = None,
    model_function: Callable[..., float] | None = None,
    polynomial_function: Callable[..., object] | None = None,
) -> bool:
    run_at = now or datetime.now(timezone.utc)
    local_now = run_at.astimezone(LONDON)
    if not force and local_now.hour != 12:
        print(f"Skipping update: it is {local_now:%H:%M} in Oxford, not the noon hour.")
        return False

    observation = observation or fetch_observation()
    record = calculate_record(
        observation,
        run_at,
        model_function,
        polynomial_function,
    )
    data = _read_data(path)
    data["current"] = record
    data["updated_at"] = run_at.isoformat()

    if local_now.hour == 12:
        history = data["history"]
        snapshot = {
            **record,
            "date": local_now.date().isoformat(),
        }
        history = [
            entry for entry in history if entry.get("date") != snapshot["date"]
        ]
        history.append(snapshot)
        history.sort(key=lambda entry: entry["date"])
        data["history"] = history[-HISTORY_LIMIT:]

    _write_data(path, data)
    print(f"Updated UTCI data from station observation at {observation.observed_at:%Y-%m-%d %H:%M:%S %Z}.")
    return True


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description="Fetch Oxford roof-station observations and calculate UTCI."
    )
    argument_parser.add_argument(
        "--force",
        action="store_true",
        help="Run now instead of waiting for the Oxford noon update window.",
    )
    arguments = argument_parser.parse_args()
    data_path = Path(__file__).resolve().parents[1] / "site" / "data" / "latest.json"
    update_data(data_path, force=arguments.force)


if __name__ == "__main__":
    main()
