const inputRows = [
  ["Air temperature", "air_temperature_c", "°C"],
  ["Mean radiant temperature (assumed)", "mean_radiant_temperature_c", "°C"],
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

function formatComparedValue(record, key, unit) {
  const observed = Number(record.inputs[key]);
  const used = Number(record.model_inputs[key]);
  if (observed === used) {
    return formatValue(observed, unit);
  }
  return `${formatValue(observed, unit)} → ${formatValue(used, unit)}`;
}

function formatTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown time";
  }
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
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
  document.getElementById("neural-utci-value").textContent =
    Number(neuralValue).toFixed(1);
  document.getElementById("polynomial-utci-value").textContent =
    hasPolynomialValue(record) ? Number(record.polynomial_utci_c).toFixed(1) : "N/A";
  document.getElementById("polynomial-status").textContent =
    record.polynomial_status === "outside_model_range"
      ? "An input is outside the polynomial model's valid range."
      : "";
  document.getElementById("observation-time").textContent =
    `Station observation: ${formatTimestamp(record.observed_at)} Oxford time`;
  document.getElementById("calculation-time").textContent =
    `Calculated: ${formatTimestamp(record.calculated_at)} Oxford time`;

  const body = document.getElementById("current-inputs");
  for (const [label, key, unit] of inputRows) {
    const row = document.createElement("tr");
    addCell(row, label);
    addCell(row, formatValue(record.inputs[key], unit));
    addCell(row, formatValue(record.model_inputs[key], unit));
    body.append(row);
  }

  document.getElementById("current-calculation").hidden = false;
  document.getElementById("load-status").hidden = true;
}

function renderHistory(records) {
  if (!records.length) {
    return;
  }

  const body = document.getElementById("history-rows");
  for (const record of [...records].reverse()) {
    const row = document.createElement("tr");
    addCell(row, record.date);
    addCell(row, formatTimestamp(record.calculated_at));
    addCell(row, formatTimestamp(record.observed_at));
    const neuralValue = record.neural_utci_c ?? record.utci_c;
    addCell(row, `${Number(neuralValue).toFixed(1)} °C`);
    addCell(
      row,
      hasPolynomialValue(record)
        ? `${Number(record.polynomial_utci_c).toFixed(1)} °C`
        : "N/A",
    );
    addCell(row, formatComparedValue(record, "air_temperature_c", "°C"));
    addCell(row, formatComparedValue(record, "mean_radiant_temperature_c", "°C"));
    addCell(row, formatComparedValue(record, "relative_humidity_percent", "%"));
    addCell(row, formatComparedValue(record, "wind_speed_m_s", "m/s"));
    body.append(row);
  }

  document.getElementById("history-empty").hidden = true;
  document.getElementById("history-table").hidden = false;
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
  renderHistory(data.history ?? []);
}

loadData().catch((error) => {
  document.getElementById("load-status").textContent =
    `Could not load the latest UTCI data: ${error.message}`;
});
