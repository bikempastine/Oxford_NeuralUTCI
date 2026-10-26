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
    classify_thermal_stress,
    exact_shapley_values,
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
    def test_exact_shapley_values_sum_to_prediction_difference(self) -> None:
        reference = (0.0, 0.0, 0.0, 0.0)
        current = (1.0, 1.0, 0.0, 0.0)

        def predict(values: tuple[float, ...]) -> float:
            first, second, _, _ = values
            return 5.0 + 2.0 * first + 3.0 * second + first * second

        reference_prediction, contributions = exact_shapley_values(
            current,
            reference,
            predict,
        )
        self.assertEqual(reference_prediction, 5.0)
        self.assertAlmostEqual(contributions["air_temperature_c"], 2.5)
        self.assertAlmostEqual(
            contributions["mrt_minus_air_temperature_c"],
            3.5,
        )
        self.assertAlmostEqual(sum(contributions.values()), 6.0)

    def test_shap_rejects_wrong_feature_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 4 inputs"):
            exact_shapley_values((1.0,), (0.0,), lambda values: sum(values))

    def test_thermal_stress_categories_at_thresholds(self) -> None:
        cases = (
            (46.1, "Extreme heat stress"),
            (46.0, "Very strong heat stress"),
            (38.0, "Very strong heat stress"),
            (32.0, "Strong heat stress"),
            (26.0, "Moderate heat stress"),
            (9.0, "No thermal stress"),
            (0.0, "Slight cold stress"),
            (-13.0, "Moderate cold stress"),
            (-27.0, "Strong cold stress"),
            (-40.0, "Very strong cold stress"),
            (-40.1, "Extreme cold stress"),
            (None, None),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(classify_thermal_stress(value), expected)

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
        self.assertEqual(record["neural_stress_category"], "Slight cold stress")
        self.assertEqual(record["polynomial_utci_c"], 3.8)
        self.assertEqual(record["polynomial_status"], "calculated")
        self.assertEqual(record["polynomial_stress_category"], "Slight cold stress")
        self.assertEqual(record["inputs"]["wind_speed_m_s"], 0.0)
        self.assertEqual(
            record["shap"]["reference_inputs"]["air_temperature_c"],
            20.0,
        )
        self.assertEqual(record["shap"]["neural"]["reference_utci_c"], 4.26)
        self.assertEqual(
            record["shap"]["polynomial"]["reference_utci_c"],
            3.84,
        )
        self.assertTrue(
            all(
                abs(value) < 1e-12
                for value in record["shap"]["neural"]["contributions_c"].values()
            )
        )

    def test_neural_and_polynomial_shap_use_their_own_model_predictions(self) -> None:
        observation = Observation(
            observed_at=datetime(2026, 10, 22, 21, 18, tzinfo=timezone.utc),
            air_temperature_c=12.0,
            relative_humidity_percent=65.0,
            wind_speed_m_s=2.0,
        )

        def neural_model(
            *, Ta: float, Tr: float, va: float, rH: float, oob: str
        ) -> float:
            return 3.0 + Ta + 2.0 * Tr + 5.0 * va + 0.03 * rH + 0.1 * Ta * va

        def polynomial_model(
            *,
            tdb: float,
            tr: float,
            v: float,
            rh: float,
            units: str,
            limit_inputs: bool,
            round_output: bool,
        ) -> SimpleNamespace:
            return SimpleNamespace(
                utci=-2.0 + 0.8 * tdb + 0.25 * tr + 1.2 * v - 0.01 * rh
                + 0.05 * tdb * rh
            )

        record = calculate_record(
            observation,
            model_function=neural_model,
            polynomial_function=polynomial_model,
        )
        shap = record["shap"]
        current = (
            observation.air_temperature_c,
            0.0,
            observation.wind_speed_m_s,
            observation.relative_humidity_percent,
        )

        expected_predictions = {
            "neural": neural_model(
                Ta=current[0],
                Tr=current[0] + current[1],
                va=current[2],
                rH=current[3],
                oob="clamp",
            ),
            "polynomial": polynomial_model(
                tdb=current[0],
                tr=current[0] + current[1],
                v=current[2],
                rh=current[3],
                units="SI",
                limit_inputs=True,
                round_output=False,
            ).utci,
        }
        for contribution_key in ("neural", "polynomial"):
            explanation = shap[contribution_key]
            self.assertAlmostEqual(
                explanation["reference_utci_c"]
                + sum(explanation["contributions_c"].values()),
                expected_predictions[contribution_key],
                places=10,
            )

        for contribution_key, output_key in (
            ("neural", "neural_utci_c"),
            ("polynomial", "polynomial_utci_c"),
        ):
            self.assertAlmostEqual(
                round(expected_predictions[contribution_key], 1),
                float(record[output_key]),
                places=10,
            )

        self.assertNotEqual(
            shap["neural"]["contributions_c"],
            shap["polynomial"]["contributions_c"],
        )

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
            self.assertEqual(history[-1]["neural_stress_category"], "Slight cold stress")
            self.assertEqual(history[-1]["polynomial_stress_category"], "Slight cold stress")
            self.assertNotIn("model_inputs", history[-1])

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
                now=datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc),
                observation=observation,
                model_function=lambda **kwargs: 8.0,
                polynomial_function=lambda **kwargs: SimpleNamespace(utci=7.5),
            )
            self.assertTrue(updated)
            data = json.loads(path.read_text())
            self.assertIsNotNone(data["current"])
            self.assertEqual(data["history"], [])


if __name__ == "__main__":
    unittest.main()
