# Oxford Neural-UTCI

A simple GitHub Pages site that explains how Oxford feels using UTCI calculated
from current observations at the Physics roof station.

## What the site displays

- The latest station observation time, UTCI result, and every input used for
  both the Neural-UTCI and polynomial calculations.
- Only the station readings used in each calculation, plus the clearly
  identified mean radiant temperature assumption.
- Short descriptions of the neural-network and polynomial UTCI methods.
- A colour-coded thermal-stress category for each model result, following the
  temperature bands, symptoms, and general guidance shown in the category
  table on the page.
- A result panel tinted to match each model's current thermal-stress category,
  and a horizontal dashboard of the current station readings.
- The selected category's general recommendation beneath each model result.
- A hover and keyboard-accessible visual summary of how each input influences
  the model result, ranked by relative contribution size and calculated
  separately for each model.

Mean radiant temperature is assumed to equal air temperature. It is not
measured separately by this site.

## Data and calculation

The updater reads the latest values and timestamp from the
[Oxford Physics roof station's current-weather page](https://eodg.atm.ox.ac.uk/eodg/weather/weather.html).
It calls `NeuralUTCI.utci` with air temperature, mean radiant temperature equal
to air temperature, wind speed, relative humidity, and `oob="clamp"`. It also calls
`pythermalcomfort.models.utci` with the same original station inputs, SI units,
and the library's default valid-range checking. Both outputs are shown rounded
to one decimal place. If an input is outside the polynomial model's valid
range, the polynomial value is recorded as unavailable rather than being
clamped; the Neural-UTCI result remains available using its own clamping rule.
The colour-coded stress categories are assigned to the rounded UTCI values
using the thresholds shown on the page.
The input influence summary uses exact Shapley attribution across the model's
four inputs, with reference conditions of 20 °C air temperature, mean radiant
temperature equal to air temperature, 1 m/s wind, and 50% relative humidity.
Neural-UTCI and the polynomial model are evaluated independently for each
reference/current input combination; each explanation's contributions sum to
that model's change from its own reference prediction.
The display shows air temperature, wind, and relative humidity, ranked by
direction and relative magnitude; it does not display exact contribution
values. These are model explanations, not causal effects.
The polynomial implementation's validity limits include −50 to 50 °C air
temperature, 0.5 to 17 m/s wind speed, and 0 to 100% relative humidity. Since
mean radiant temperature is assumed equal to air temperature here, the
radiant-temperature-to-air-temperature difference is zero.

Neural-UTCI's documented input ranges are air temperature −50 to 50 °C, mean
radiant temperature −80 to 120 °C, wind speed 0.5 to 30.3 m/s, and relative
humidity 5 to 100%.
When a value falls outside a model's valid range, Neural-UTCI clamps it while
the polynomial returns no result. The website displays the station reading,
not a separate table of adjusted model inputs. Wind speed is used as reported,
with no adjustment to the model's documented 10 m reference. The station
documents that its humidity sensor can briefly report 0% in saturated
conditions.

The station notes that its measurements are provided without a warranty and
are intended for non-commercial use. Please cite the station and its current
operator if using these data in published research.

## Run locally

Python 3.11 or newer is recommended.

```powershell
python -m pip install -r requirements.txt
python scripts\update_utci.py
python -m unittest discover -s tests
python -m http.server 8000 --directory site
```

The updater fetches the current observation and writes `site/data/latest.json`.
The GitHub Actions workflow refreshes the current reading hourly. It records
history only during the Oxford-local noon hour, retaining up to seven daily
readings. Daily history remains stored in the data file but is not shown on
the website.

## GitHub Actions and Pages

The workflow runs hourly, on pushes to `main`, and on manual dispatches to
refresh the current reading and deploy the site. It saves one history record
per Oxford day during the local noon hour, pushes updated data to the current
branch, and deploys the `site` folder to GitHub Pages. GitHub may delay
scheduled workflows, so hourly refreshes are best effort.

To publish:

1. In the repository's **Settings → Pages**, select **GitHub Actions** as the
   build and deployment source if it is not already selected.
2. In **Settings → Actions → General → Workflow permissions**, allow
   read/write repository permissions so the workflow can save its daily data.
3. Push this project to the `bikempastine/Oxford_NeuralUTCI` repository. That
   push starts the workflow, which calculates the first current reading and
   deploys the site.
4. If the workflow did not run on the push, use **Actions → Update and deploy
   Oxford UTCI → Run workflow** to create the first reading and publish.

Hourly automatic refreshes and daily history start after the workflow is
enabled; history begins with the first run during Oxford local noon.
