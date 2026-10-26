const inputRows = [
  ["Air temperature", "air_temperature_c", "°C"],
  ["Relative humidity", "relative_humidity_percent", "%"],
  ["Wind speed", "wind_speed_m_s", "m/s"],
];

const shapRows = [
  ["Air temperature", "air_temperature_c"],
  ["Wind speed", "wind_speed_m_s"],
  ["Relative humidity", "relative_humidity_percent"],
];

const categoryClasses = {
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

function formatValue(value, unit) {
  return `${Number(value).toFixed(1)} ${unit}`;
}

function hasPolynomialValue(record) {
  return record.polynomial_utci_c !== null &&
    record.polynomial_utci_c !== undefined &&
    Number.isFinite(Number(record.polynomial_utci_c));
}

function categoryClass(category) {
  return categoryClasses[category] ?? "";
}

function setResultCategory(element, category) {
  for (const stressClass of Object.values(categoryClasses)) {
    element.classList.remove(`stress-${stressClass}`);
  }
  const stressClass = categoryClass(category);
  if (stressClass) {
    element.classList.add(`stress-${stressClass}`);
  }
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

function setStressGuidance(element, category) {
  const matchingRow = Array.from(
    document.querySelectorAll(".guidance-table tbody tr"),
  ).find((row) => row.cells[0].textContent.trim() === category);
  if (matchingRow) {
    const label = document.createElement("span");
    label.className = "guidance-label";
    label.textContent = "General recommendation";

    const recommendation = document.createElement("span");
    recommendation.className = "guidance-text";
    recommendation.textContent = matchingRow.cells[3].textContent.trim();

    element.replaceChildren(label, recommendation);
  }
}

function renderShap(modelName, explanation, record) {
  const referenceElement = document.getElementById(`${modelName}-shap-reference`);
  const body = document.getElementById(`${modelName}-shap-contributions`);
  if (!explanation) {
    referenceElement.textContent = modelName === "polynomial"
      ? "A contribution breakdown is unavailable because this model could not calculate a UTCI value for the current inputs."
      : "A contribution breakdown is not available for this reading yet.";
    body.textContent = "";
    return;
  }

  const referenceInputs = record.shap.reference_inputs;
  referenceElement.textContent =
    `Compared with ${Number(referenceInputs.air_temperature_c).toFixed(0)} °C air, ` +
    `${Number(referenceInputs.wind_speed_m_s).toFixed(0)} m/s wind, and ` +
    `${Number(referenceInputs.relative_humidity_percent).toFixed(0)}% humidity`;

  const influences = shapRows.map(([label, key]) => ({
    label,
    value: Number(explanation.contributions_c[key]),
  })).sort((first, second) => Math.abs(second.value) - Math.abs(first.value));
  const largestInfluence = Math.max(
    ...influences.map(({ value }) => Math.abs(value)),
  );

  for (const [index, { label, value }] of influences.entries()) {
    const item = document.createElement("li");
    item.classList.add("influence-item");
    if (value === 0 || largestInfluence === 0) {
      item.classList.add("influence-neutral");
    } else {
      const magnitude = Math.abs(value) / largestInfluence;
      item.classList.add(value > 0 ? "influence-warming" : "influence-cooling");
      item.style.setProperty("--influence-size", `${magnitude * 50}%`);
    }

    const direction = document.createElement("span");
    direction.className = "influence-direction";
    direction.setAttribute("aria-hidden", "true");
    direction.textContent = value > 0 ? "↑" : value < 0 ? "↓" : "·";

    const name = document.createElement("span");
    name.className = "influence-name";
    name.textContent = label;

    const magnitudeLabel = document.createElement("span");
    magnitudeLabel.className = "influence-magnitude";
    magnitudeLabel.textContent = value === 0 || largestInfluence === 0
      ? "No change"
      : index === 0
        ? "Largest influence"
        : Math.abs(value) / largestInfluence >= 0.6
          ? "Strong influence"
          : Math.abs(value) / largestInfluence >= 0.25
            ? "Moderate influence"
            : "Smaller influence";

    const track = document.createElement("span");
    track.className = "influence-track";
    track.setAttribute("aria-hidden", "true");
    const bar = document.createElement("span");
    bar.className = "influence-bar";
    track.append(bar);

    item.append(direction, name, magnitudeLabel, track);
    body.append(item);
  }
}

function initializeInfluencePopover(modelName) {
  const wrapper = document.getElementById(`${modelName}-explanation`);
  const button = document.getElementById(`${modelName}-utci-value`);
  const popover = document.getElementById(`${modelName}-influences`);
  let pinnedOpen = false;

  const updateVisibility = () => {
    const visible = pinnedOpen ||
      wrapper.matches(":hover") ||
      wrapper.contains(document.activeElement);
    button.setAttribute("aria-expanded", String(visible));
    popover.setAttribute("aria-hidden", String(!visible));
    wrapper.classList.toggle("is-open", visible);
  };

  wrapper.addEventListener("pointerenter", updateVisibility);
  wrapper.addEventListener("pointerleave", updateVisibility);
  wrapper.addEventListener("focusin", updateVisibility);
  wrapper.addEventListener("focusout", () => {
    requestAnimationFrame(updateVisibility);
  });
  button.addEventListener("click", () => {
    pinnedOpen = !pinnedOpen;
    updateVisibility();
  });
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

function addStationReading(container, label, value) {
  const item = document.createElement("div");
  item.className = "station-reading";
  item.setAttribute("role", "listitem");

  const name = document.createElement("span");
  name.className = "station-reading-label";
  name.textContent = label;

  const reading = document.createElement("strong");
  reading.className = "station-reading-value";
  reading.textContent = value;

  item.append(name, reading);
  container.append(item);
}

function renderCurrent(record) {
  const neuralValue = record.neural_utci_c ?? record.utci_c;
  const neuralStress = record.neural_stress_category ??
    thermalStressCategory(Number(neuralValue));
  const neuralValueElement = document.getElementById("neural-utci-value");
  const neuralResult = neuralValueElement.closest(".result");
  const neuralDescription = document.getElementById("neural-description");
  neuralDescription.textContent =
    "A neural-network model that estimates UTCI from the station's weather readings.";
  neuralValueElement.textContent = `${Number(neuralValue).toFixed(1)} °C`;
  const neuralClass = categoryClass(neuralStress);
  neuralValueElement.className = `utci-value ${neuralClass}`;
  setResultCategory(neuralResult, neuralStress);
  setStressCategory(
    document.getElementById("neural-stress-category"),
    neuralStress,
  );
  setStressGuidance(
    document.getElementById("neural-stress-guidance"),
    neuralStress,
  );
  renderShap("neural", record.shap?.neural, record);

  const polynomialValueElement = document.getElementById("polynomial-utci-value");
  const polynomialResult = polynomialValueElement.closest(".result");
  const polynomialCategoryElement = document.getElementById("polynomial-stress-category");
  document.getElementById("polynomial-description").textContent =
    "The traditional UTCI model, calculated using its established polynomial approximation.";
  if (hasPolynomialValue(record)) {
    const polynomialStress = record.polynomial_stress_category ??
      thermalStressCategory(Number(record.polynomial_utci_c));
    polynomialValueElement.textContent =
      `${Number(record.polynomial_utci_c).toFixed(1)} °C`;
    const polynomialClass = categoryClass(polynomialStress);
    polynomialValueElement.className = `utci-value ${polynomialClass}`;
    setResultCategory(polynomialResult, polynomialStress);
    setStressCategory(polynomialCategoryElement, polynomialStress);
    setStressGuidance(
      document.getElementById("polynomial-stress-guidance"),
      polynomialStress,
    );
  } else {
    polynomialValueElement.textContent = "N/A";
    polynomialValueElement.className = "utci-value";
    setResultCategory(polynomialResult, "");
    polynomialCategoryElement.textContent = "Unavailable";
    document.getElementById("polynomial-stress-guidance").textContent = "";
  }
  renderShap("polynomial", record.shap?.polynomial, record);
  document.getElementById("polynomial-status").textContent =
    record.polynomial_status === "outside_model_range"
      ? "An input is outside the polynomial model's valid range."
      : "";
  document.getElementById("latest-heading").textContent =
    `Oxford UTCI last updated ${formatTimestamp(record.observed_at)}.`;

  const body = document.getElementById("current-inputs");
  for (const [label, key, unit] of inputRows) {
    addStationReading(body, label, formatValue(record.inputs[key], unit));
  }
  addStationReading(body, "Mean radiant temperature", "Not measured");

  document.getElementById("current-calculation").hidden = false;
  document.getElementById("load-status").hidden = true;
}

initializeInfluencePopover("neural");
initializeInfluencePopover("polynomial");

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
