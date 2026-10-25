# Oxford Neural-UTCI

A simple GitHub Pages site that displays UTCI calculated from the current
weather observations at the Oxford Physics roof station.

## What the site displays

- The latest station observation time, UTCI result, and every input used for
  both the Neural-UTCI and polynomial calculations.
- Only the station readings used in each calculation, plus the clearly
  identified MRT assumption.
- A colour-coded thermal-stress category for each model result, following the
  temperature bands shown on the page.

Mean radiant temperature (MRT) is assumed to equal air temperature. It is not
measured separately by this site.

## Data and calculation

The updater reads the latest values and timestamp from the
[Oxford Physics roof station's current-weather page](https://eodg.atm.ox.ac.uk/eodg/weather/weather.html).
It calls `NeuralUTCI.utci` with air temperature, MRT equal to air temperature,
wind speed, relative humidity, and `oob="clamp"`. It also calls
`pythermalcomfort.models.utci` with the same original station inputs, SI units,
and the library's default valid-range checking. Both outputs are shown rounded
to one decimal place. If an input is outside the polynomial model's valid
range, the polynomial value is recorded as unavailable rather than being
clamped; the Neural-UTCI result remains available using its own clamping rule.
The colour-coded stress categories are assigned to the rounded UTCI values
using the thresholds shown on the page.
The polynomial implementation's validity limits include −50 to 50 °C air
temperature, 0.5 to 17 m/s wind speed, and 0 to 100% relative humidity. Since
MRT is assumed equal to air temperature here, the MRT-to-air-temperature
difference is zero.

Neural-UTCI's documented input ranges are air temperature −50 to 50 °C, MRT
−80 to 120 °C, wind speed 0.5 to 30.3 m/s, and relative humidity 5 to 100%.
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
python scripts\update_utci.py --force
python -m unittest discover -s tests
python -m http.server 8000 --directory site
```

The updater fetches the current observation and writes `site/data/latest.json`.
It records history only during the Oxford-local noon hour; `--force` allows the
current reading to be refreshed at another time without creating a non-noon
history entry. Daily history remains stored in the data file but is not shown
on the website.

## GitHub Actions and Pages

The workflow runs on pushes to `main` and manual dispatches to create or refresh
the current reading. It checks both 11:15 and 12:15 UTC for its scheduled daily
run so one check falls in the Oxford noon hour in either GMT or British Summer
Time. Scheduled runs save one history record per Oxford day, push the updated
data file to the current branch, and deploy the `site` folder to GitHub Pages.
GitHub may delay scheduled workflows.

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

The automatic daily history starts with the first run during Oxford local noon.
