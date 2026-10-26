from __future__ import annotations

import argparse
import csv
import io
import json
import tempfile
from pathlib import Path

import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from sklearn.linear_model import LinearRegression


FEATURE_NAMES = ("Ta", "Tr-Ta", "va", "rH")
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1] / "site" / "data" / "polynomial_model.json"
)


def train_model(training_data: Path, output: Path = DEFAULT_OUTPUT) -> None:
    with training_data.open(encoding="utf-8-sig", newline="") as source:
        table = "\n".join(
            line for line in source if line.strip() and not line.startswith("*")
        )
    rows = list(csv.DictReader(io.StringIO(table), delimiter="\t"))
    if not rows or any(name not in rows[0] for name in (*FEATURE_NAMES, "Offset")):
        raise ValueError(
            f"{training_data} must contain {', '.join((*FEATURE_NAMES, 'Offset'))}."
        )

    inputs = np.asarray(
        [[float(row[name]) for name in FEATURE_NAMES] for row in rows],
        dtype=float,
    )
    targets = np.asarray([float(row["Offset"]) for row in rows], dtype=float)
    x_train, _, y_train, _ = train_test_split(
        inputs,
        targets,
        random_state=0,
        train_size=0.90,
    )

    scaler = StandardScaler()
    polynomial_features = PolynomialFeatures(degree=6, include_bias=False)
    x_train_scaled = scaler.fit_transform(x_train)
    x_train_polynomial = polynomial_features.fit_transform(x_train_scaled)
    regression = LinearRegression()
    regression.fit(x_train_polynomial, y_train)

    model = {
        "feature_names": FEATURE_NAMES,
        "target": "UTCI offset (UTCI - air temperature)",
        "degree": 6,
        "training_rows": len(x_train),
        "training_split": {"train_size": 0.90, "random_state": 0},
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "polynomial_powers": polynomial_features.powers_.tolist(),
        "coefficients": regression.coef_.tolist(),
        "intercept": float(regression.intercept_),
        "valid_ranges": [
            [float(x_train[:, index].min()), float(x_train[:, index].max())]
            for index in range(len(FEATURE_NAMES))
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        suffix=".tmp",
        delete=False,
    ) as temporary:
        json.dump(model, temporary, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(output)
    print(f"Trained degree-6 polynomial UTCI model on {len(x_train)} rows: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train the notebook's degree-6 polynomial UTCI model."
    )
    parser.add_argument(
        "training_data",
        type=Path,
        help="Path to ESM_4_Table_Offset.Dat from the notebook's training data.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    train_model(arguments.training_data, arguments.output)


if __name__ == "__main__":
    main()
