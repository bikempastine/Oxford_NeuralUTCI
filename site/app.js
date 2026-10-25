const inputRows = [
  ["Air temperature", "air_temperature_c", "°C"],
  ["Relative humidity", "relative_humidity_percent", "%"],
  ["Wind speed", "wind_speed_m_s", "m/s"],
];

function formatValue(value, unit) {
  return `${Number(value).toFixed(1)} ${unit}`;
}

function hasPolynomialValue(record) {
  return record.polynomial_utci_c !== null &&
    record.polynomial_utci_c !== undefined &&
    Number.isFinite(Number(record.polynomial_utci_c));
}

function categoryClass(category) {
  const classes = {
    "Extreme heat stress": "extreme-heat",
    "Very strong heat stress": "very-strong-heat",
    "Strong heat stress": "strong-heat",
    "Moderate heat stress": "moderate-heat",
    "No thermal stress": "no-stress",
    "Slight cold stress": "slight-cold",
    "Moderate cold stress": "moderate-cold",
    "Strong cold stress": "strong-cold",
    "Very strong cold stress": "very-strong-cold",
    "Extreme cold stress": "extreme-cold",
  };
  return classes[category] ?? "";
}

function thermalStressCategory(value) {
  if (value > 46) return "Extreme heat stress";
  if (value >= 38) return "Very strong heat stress";
  if (value >= 32) return "Strong heat stress";
  if (value >= 26) return "Moderate heat stress";
  if (value >= 9) return "No thermal stress";
  if (value >= 0) return "Slight cold stress";
  if (value >= -13) return "Moderate cold stress";
  if (value >= -27) return "Strong cold stress";
  if (value >= -40) return "Very strong cold stress";
  return "Extreme cold stress";
}

function setStressCategory(element, category) {
  element.textContent = category;
  const stressClass = categoryClass(category);
  if (stressClass) {
    element.classList.add(stressClass);
  }
}

function formatTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown time";
  }
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  }).format(date);
}

function addCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  row.append(cell);
}

function renderCurrent(record) {
  const neuralValue = record.neural_utci_c ?? record.utci_c;
  const neuralStress = record.neural_stress_category ??
    thermalStressCategory(Number(neuralValue));
  const neuralValueElement = document.getElementById("neural-utci-value");
  neuralValueElement.textContent = `${Number(neuralValue).toFixed(1)} °C`;
  const neuralClass = categoryClass(neuralStress);
  if (neuralClass) {
    neuralValueElement.classList.add(neuralClass);
  }
  setStressCategory(
    document.getElementById("neural-stress-category"),
    neuralStress,
  );

  const polynomialValueElement = document.getElementById("polynomial-utci-value");
  const polynomialCategoryElement = document.getElementById("polynomial-stress-category");
  if (hasPolynomialValue(record)) {
    const polynomialStress = record.polynomial_stress_category ??
      thermalStressCategory(Number(record.polynomial_utci_c));
    polynomialValueElement.textContent =
      `${Number(record.polynomial_utci_c).toFixed(1)} °C`;
    const polynomialClass = categoryClass(polynomialStress);
    if (polynomialClass) {
      polynomialValueElement.classList.add(polynomialClass);
    }
    setStressCategory(polynomialCategoryElement, polynomialStress);
  } else {
    polynomialValueElement.textContent = "N/A";
    polynomialCategoryElement.textContent = "Unavailable";
  }
  document.getElementById("polynomial-status").textContent =
    record.polynomial_status === "outside_model_range"
      ? "An input is outside the polynomial model's valid range."
      : "";
  document.getElementById("reading-datetime").textContent =
    `${formatTimestamp(record.observed_at)}.`;
  document.getElementById("calculation-time").textContent =
    `UTCI calculated: ${formatTimestamp(record.calculated_at)} Oxford time`;

  const body = document.getElementById("current-inputs");
  for (const [label, key, unit] of inputRows) {
    const row = document.createElement("tr");
    addCell(row, label);
    addCell(row, formatValue(record.inputs[key], unit));
    body.append(row);
  }
  const mrtRow = document.createElement("tr");
  addCell(mrtRow, "Mean radiant temperature (MRT)");
  addCell(mrtRow, "-");
  body.append(mrtRow);

  document.getElementById("current-calculation").hidden = false;
  document.getElementById("load-status").hidden = true;
}

async function loadData() {
  const response = await fetch("data/latest.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`The data file could not be loaded (HTTP ${response.status}).`);
  }
  const data = await response.json();
  if (data.current) {
    renderCurrent(data.current);
  } else {
    document.getElementById("load-status").textContent =
      "The first calculation has not run yet. It will appear after the workflow is started.";
  }
}

loadData().catch((error) => {
  document.getElementById("load-status").textContent =
    `Could not load the latest UTCI data: ${error.message}`;
});
