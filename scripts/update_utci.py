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
SHAP_INPUTS = (
    "air_temperature_c",
    "mrt_minus_air_temperature_c",
    "wind_speed_m_s",
    "relative_humidity_percent",
)
SHAP_REFERENCE = {
    "air_temperature_c": 20.0,
    "mrt_minus_air_temperature_c": 0.0,
    "wind_speed_m_s": 1.0,
    "relative_humidity_percent": 50.0,
}
POLYNOMIAL_MODEL_PATH = (
    Path(__file__).resolve().parents[1] / "site" / "data" / "polynomial_model.json"
)

STRESS_CATEGORIES = (
    (38.0, "Very strong heat stress"),
    (32.0, "Strong heat stress"),
    (26.0, "Moderate heat stress"),
    (9.0, "No thermal stress"),
    (0.0, "Slight cold stress"),
    (-13.0, "Moderate cold stress"),
    (-27.0, "Strong cold stress"),
    (-40.0, "Very strong cold stress"),
)


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    air_temperature_c: float
    relative_humidity_percent: float
    wind_speed_m_s: float


@dataclass(frozen=True)
class PolynomialUTCIModel:
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    polynomial_powers: tuple[tuple[int, ...], ...]
    coefficients: tuple[float, ...]
    intercept: float
    valid_ranges: tuple[tuple[float, float], ...]

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> PolynomialUTCIModel:
        if data.get("feature_names") != list(("Ta", "Tr-Ta", "va", "rH")):
            raise ValueError("The trained polynomial UTCI model has unexpected inputs.")
        if data.get("degree") != 6:
            raise ValueError("The trained polynomial UTCI model must use degree six.")
        mean = tuple(float(value) for value in data["scaler_mean"])
        scale = tuple(float(value) for value in data["scaler_scale"])
        powers = tuple(
            tuple(int(power) for power in row)
            for row in data["polynomial_powers"]
        )
        coefficients = tuple(float(value) for value in data["coefficients"])
        ranges = tuple(
            (float(row[0]), float(row[1]))
            for row in data["valid_ranges"]
        )
        intercept = float(data["intercept"])
        feature_count = len(SHAP_INPUTS)
        if (
            len(mean) != feature_count
            or len(scale) != feature_count
            or len(ranges) != feature_count
            or not powers
            or len(powers) != len(coefficients)
            or any(len(row) != feature_count for row in powers)
            or any(not math.isfinite(value) for value in (*mean, *scale, *coefficients, intercept))
            or any(scale_value <= 0 for scale_value in scale)
            or any(
                not math.isfinite(bound) or low > high
                for low, high in ranges
                for bound in (low, high)
            )
        ):
            raise ValueError("The trained polynomial UTCI model has invalid parameters.")
        return cls(mean, scale, powers, coefficients, intercept, ranges)

    @classmethod
    def load(cls, path: Path = POLYNOMIAL_MODEL_PATH) -> PolynomialUTCIModel:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected polynomial model format in {path}.")
        return cls.from_dict(data)

    def accepts(self, values: tuple[float, ...]) -> bool:
        return len(values) == len(self.valid_ranges) and all(
            low <= value <= high
            for value, (low, high) in zip(values, self.valid_ranges)
        )

    def predict_utci(self, values: tuple[float, ...]) -> float:
        if len(values) != len(SHAP_INPUTS):
            raise ValueError("Polynomial UTCI requires exactly four model inputs.")
        scaled = tuple(
            (value - mean) / scale
            for value, mean, scale in zip(values, self.scaler_mean, self.scaler_scale)
        )
        offset = self.intercept + math.fsum(
            coefficient
            * math.prod(scaled[index] ** power for index, power in enumerate(powers))
            for coefficient, powers in zip(self.coefficients, self.polynomial_powers)
        )
        return values[0] + offset


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


def classify_thermal_stress(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    if value > 46.0:
        return "Extreme heat stress"
    for threshold, category in STRESS_CATEGORIES:
        if value >= threshold:
            return category
    return "Extreme cold stress"


def exact_shapley_values(
    current_values: tuple[float, ...],
    reference_values: tuple[float, ...],
    predict: Callable[[tuple[float, ...]], float],
) -> tuple[float, dict[str, float]]:
    feature_count = len(SHAP_INPUTS)
    if len(current_values) != feature_count or len(reference_values) != feature_count:
        raise ValueError(f"SHAP calculations require exactly {feature_count} inputs.")

    coalition_values: dict[int, float] = {}
    for coalition in range(1 << feature_count):
        values = tuple(
            current_values[index]
            if coalition & (1 << index)
            else reference_values[index]
            for index in range(feature_count)
        )
        prediction = predict(values)
        if not math.isfinite(prediction):
            raise ValueError("A model returned a non-finite value during SHAP calculation.")
        coalition_values[coalition] = prediction

    contributions: dict[str, float] = {}
    for feature_index, feature_name in enumerate(SHAP_INPUTS):
        contribution = 0.0
        feature_bit = 1 << feature_index
        for coalition in range(1 << feature_count):
            if coalition & feature_bit:
                continue
            coalition_size = coalition.bit_count()
            weight = 1.0 / (
                feature_count * math.comb(feature_count - 1, coalition_size)
            )
            contribution += weight * (
                coalition_values[coalition | feature_bit]
                - coalition_values[coalition]
            )
        contributions[feature_name] = contribution

    return coalition_values[0], contributions


def calculate_record(
    observation: Observation,
    calculated_at: datetime | None = None,
    model_function: Callable[..., float] | None = None,
    polynomial_function: Callable[[tuple[float, ...]], float] | None = None,
) -> dict[str, object]:
    if model_function is None:
        from NeuralUTCI import utci

        model_function = utci
    polynomial_model = PolynomialUTCIModel.load()
    predict_polynomial_model = polynomial_function or polynomial_model.predict_utci

    raw_inputs = {
        "air_temperature_c": observation.air_temperature_c,
        "mean_radiant_temperature_c": observation.air_temperature_c,
        "wind_speed_m_s": observation.wind_speed_m_s,
        "relative_humidity_percent": observation.relative_humidity_percent,
    }
    current_shap_inputs = (
        observation.air_temperature_c,
        0.0,
        observation.wind_speed_m_s,
        observation.relative_humidity_percent,
    )
    reference_shap_inputs = tuple(SHAP_REFERENCE[name] for name in SHAP_INPUTS)

    def predict_neural(values: tuple[float, ...]) -> float:
        air_temperature, mrt_difference, wind_speed, humidity = values
        return float(
            model_function(
                Ta=air_temperature,
                Tr=air_temperature + mrt_difference,
                va=wind_speed,
                rH=humidity,
                oob="clamp",
            )
        )

    neural_reference_value, neural_contributions = exact_shapley_values(
        current_shap_inputs,
        reference_shap_inputs,
        predict_neural,
    )
    value = predict_neural(current_shap_inputs)
    if not math.isfinite(value):
        raise ValueError("Neural-UTCI returned a non-finite UTCI value.")

    polynomial_value: float | None = None
    polynomial_explanation: dict[str, object] | None = None
    if polynomial_model.accepts(current_shap_inputs):
        result_value = predict_polynomial_model(current_shap_inputs)
        if math.isfinite(result_value):
            polynomial_value = round(result_value, 1)
            polynomial_reference_value, polynomial_contributions = exact_shapley_values(
                current_shap_inputs,
                reference_shap_inputs,
                predict_polynomial_model,
            )
            polynomial_explanation = {
                "reference_utci_c": polynomial_reference_value,
                "contributions_c": polynomial_contributions,
            }

    return {
        "observed_at": observation.observed_at.isoformat(),
        "calculated_at": (calculated_at or datetime.now(timezone.utc)).isoformat(),
        "utci_c": round(value, 1),
        "neural_utci_c": round(value, 1),
        "neural_stress_category": classify_thermal_stress(round(value, 1)),
        "polynomial_utci_c": polynomial_value,
        "polynomial_status": (
            "calculated" if polynomial_value is not None else "outside_model_range"
        ),
        "polynomial_stress_category": classify_thermal_stress(polynomial_value),
        "inputs": raw_inputs,
        "shap": {
            "reference_inputs": SHAP_REFERENCE,
            "neural": {
                "reference_utci_c": neural_reference_value,
                "contributions_c": neural_contributions,
            },
            "polynomial": polynomial_explanation,
        },
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
    now: datetime | None = None,
    observation: Observation | None = None,
    model_function: Callable[..., float] | None = None,
    polynomial_function: Callable[..., object] | None = None,
) -> bool:
    run_at = now or datetime.now(timezone.utc)
    local_now = run_at.astimezone(LONDON)
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
    argument_parser.parse_args()
    data_path = Path(__file__).resolve().parents[1] / "site" / "data" / "latest.json"
    update_data(data_path)


if __name__ == "__main__":
    main()
