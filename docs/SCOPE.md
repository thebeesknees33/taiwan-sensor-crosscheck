# Scope and guardrails

## What this project is

- **Comparative measurement:** quantifying agreement, bias and error between independent public data sources.
- **Civilian protective information:** earthquakes, weather, ocean conditions, public shelters.
- **Anomaly detection as a data-quality question:** e.g. a vessel that appears in one source but not another where it would be expected.
- **Open data only:** public feeds used within their terms of service and licenses, with attribution.

## What this project is not

- Not for tracking military units or forecasting force posture.
- Not for predicting the timing or tactics of any conflict.
- Not a public warning or alerting system. Official sources (e.g. CWA alerts) are the authority for safety decisions.
- Not for targeting or operational tasking of any kind.

## Data handling

- API keys live in environment variables (e.g. `CWA_API_KEY`), never in the repo.
- Each source's license and attribution requirement is recorded alongside the collector that uses it.
- Network sends (e.g. to a TAK server) are opt-in and off by default.
