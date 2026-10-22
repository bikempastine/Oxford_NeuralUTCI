import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from update_utci import (  # noqa: E402
    Observation,
    calculate_record,
    parse_station_page,
    update_data,
)


SAMPLE_PAGE = """
<h4>22-10-2026 21:18:06 GMT</h4>
<table>
  <tr><td rowspan="6"><img src="weather.png"></td><td>Temperature</td><td>9.4 &deg;C</td></tr>
  <tr><td>Relative Humidity</td><td>84.0 %</td></tr>
  <tr><td>Wind</td><td>2.7 m/s (6.0 mph) at 114&deg;</td></tr>
</table>
"""


class UpdateUTCITests(unittest.TestCase):
    def test_parse_station_page(self) -> None:
        observation = parse_station_page(SAMPLE_PAGE)
        self.assertEqual(
            observation,
            Observation(
                observed_at=datetime(2026, 10, 22, 21, 18, 6, tzinfo=timezone.utc),
                air_temperature_c=9.4,
                relative_humidity_percent=84.0,
                wind_speed_m_s=2.7,
            ),
        )

    def test_missing_station_field_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing expected fields"):
            parse_station_page("<h4>22-10-2026 21:18:06 GMT</h4>")

    def test_calculate_record_uses_requested_inputs_and_clamp_mode(self) -> None:
        observation = Observation(
            observed_at=datetime(2026, 10, 22, 21, 18, tzinfo=timezone.utc),
            air_temperature_c=9.4,
            relative_humidity_percent=0.0,
            wind_speed_m_s=0.0,
        )
        calls = {}
        polynomial_calls = {}

        def fake_model(**kwargs: float) -> float:
            calls.update(kwargs)
            return 4.26

        def fake_polynomial(**kwargs: object) -> SimpleNamespace:
            polynomial_calls.update(kwargs)
            return SimpleNamespace(utci=3.84)

        record = calculate_record(
            observation,
            model_function=fake_model,
            polynomial_function=fake_polynomial,
        )
        self.assertEqual(
            calls,
            {"Ta": 9.4, "Tr": 9.4, "va": 0.0, "rH": 0.0, "oob": "clamp"},
        )
        self.assertEqual(
            polynomial_calls,
            {
                "tdb": 9.4,
                "tr": 9.4,
                "v": 0.0,
                "rh": 0.0,
                "units": "SI",
                "limit_inputs": True,
                "round_output": False,
            },
        )
        self.assertEqual(record["utci_c"], 4.3)
        self.assertEqual(record["neural_utci_c"], 4.3)
        self.assertEqual(record["polynomial_utci_c"], 3.8)
        self.assertEqual(record["polynomial_status"], "calculated")
        self.assertEqual(record["inputs"]["wind_speed_m_s"], 0.0)
        self.assertEqual(record["model_inputs"]["wind_speed_m_s"], 0.5)
        self.assertEqual(record["model_inputs"]["relative_humidity_percent"], 5.0)

    def test_polynomial_result_is_unavailable_when_outside_its_input_range(self) -> None:
        observation = Observation(
            observed_at=datetime(2026, 10, 22, 21, 18, tzinfo=timezone.utc),
            air_temperature_c=9.4,
            relative_humidity_percent=84.0,
            wind_speed_m_s=20.0,
        )
        record = calculate_record(
            observation,
            model_function=lambda **kwargs: 18.0,
            polynomial_function=lambda **kwargs: SimpleNamespace(utci=float("nan")),
        )
        self.assertIsNone(record["polynomial_utci_c"])
        self.assertEqual(record["polynomial_status"], "outside_model_range")

    def test_polynomial_is_not_called_for_invalid_humidity(self) -> None:
        observation = Observation(
            observed_at=datetime(2026, 10, 22, 21, 18, tzinfo=timezone.utc),
            air_temperature_c=9.4,
            relative_humidity_percent=120.0,
            wind_speed_m_s=2.7,
        )

        def unexpected_polynomial_call(**kwargs: object) -> SimpleNamespace:
            raise AssertionError("The polynomial should not receive invalid humidity.")

        record = calculate_record(
            observation,
            model_function=lambda **kwargs: 8.0,
            polynomial_function=unexpected_polynomial_call,
        )
        self.assertIsNone(record["polynomial_utci_c"])
        self.assertEqual(record["polynomial_status"], "outside_model_range")

    def test_noon_history_is_idempotent_and_keeps_seven_days(self) -> None:
        observation = Observation(
            observed_at=datetime(2026, 10, 22, 11, 58, tzinfo=timezone.utc),
            air_temperature_c=9.4,
            relative_humidity_percent=84.0,
            wind_speed_m_s=2.7,
        )
        fake_model = lambda **kwargs: 8.0
        fake_polynomial = lambda **kwargs: SimpleNamespace(utci=7.5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            for day in range(1, 10):
                run_at = datetime(2026, 10, day, 11, 15, tzinfo=timezone.utc)
                update_data(
                    path,
                    now=run_at,
                    observation=observation,
                    model_function=fake_model,
                    polynomial_function=fake_polynomial,
                )

            update_data(
                path,
                now=datetime(2026, 10, 9, 11, 30, tzinfo=timezone.utc),
                observation=observation,
                model_function=fake_model,
                polynomial_function=fake_polynomial,
            )
            history = json.loads(path.read_text(encoding="utf-8"))["history"]
            self.assertEqual(len(history), 7)
            self.assertEqual(history[0]["date"], "2026-10-03")
            self.assertEqual(history[-1]["date"], "2026-10-09")

    def test_non_noon_update_does_not_write_history(self) -> None:
        observation = Observation(
            observed_at=datetime(2026, 10, 22, 11, 58, tzinfo=timezone.utc),
            air_temperature_c=9.4,
            relative_humidity_percent=84.0,
            wind_speed_m_s=2.7,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            updated = update_data(
                path,
                force=True,
                now=datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc),
                observation=observation,
                model_function=lambda **kwargs: 8.0,
                polynomial_function=lambda **kwargs: SimpleNamespace(utci=7.5),
            )
            self.assertTrue(updated)
            self.assertEqual(json.loads(path.read_text())["history"], [])


if __name__ == "__main__":
    unittest.main()
