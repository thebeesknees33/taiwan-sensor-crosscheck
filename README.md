# taiwan-sensor-crosscheck

An open-source tool that measures how accurate public data streams about Taiwan are. It compares independent sources that observe the same thing and records where they agree and where they disagree.

The questions it asks:

1. **Accuracy alone:** how close does each source come to the others for the same real-world event?
2. **Fusion:** does combining sources give a better estimate than any single one?
3. **Disagreement:** when sources don't match, is that noise, a systematic bias, or a real anomaly (e.g. a ship visible by satellite but silent on AIS)?

## First experiment: earthquakes

The USGS (US Geological Survey) and Taiwan's CWA (Central Weather Administration) both report earthquakes near Taiwan. They use different seismometer networks, processing and magnitude scales. Pairing their reports of the same event and measuring the differences in magnitude, epicenter, depth and timing makes a clean, low-stakes test of the comparison method.

Later pairs, once the method works: aircraft (OpenSky vs adsb.lol), ships (AIS feeds vs each other and vs Sentinel satellite detections), and ocean/weather data.

## Output

Collectors normalize each source into a common record. Optionally they emit Cursor-on-Target (CoT) XML so the data can be viewed in ATAK/WinTAK, either as files or through a TAK server such as OpenTAKServer. Nothing goes over the network to a TAK server unless you explicitly ask it to.

## Scope

This is civilian measurement science and personal study. See [docs/SCOPE.md](docs/SCOPE.md) for what the project will and won't do.

## Quick start

Needs Python 3.10+. On Windows, run this in WSL or PowerShell.

```bash
git clone https://github.com/thebeesknees33/taiwan-sensor-crosscheck.git
cd taiwan-sensor-crosscheck
python -m venv .venv
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest                             # runs offline against real saved data
```

Live comparison of this year so far (no API keys needed):

```bash
crosscheck fetch cwa --product catalog --years 2026 --out out/cwa-2026.jsonl
crosscheck fetch usgs --start 2026-01-01 --end 2026-10-01 --out out/usgs-2026.jsonl
crosscheck compare out/cwa-2026.jsonl out/usgs-2026.jsonl --min-mag 4.5 --sweep
```

If the report warns about a magnitude floor, re-run `compare` with the `--min-mag` it suggests.

What gets written:

- **The report** goes to `out/compare/report.md`, with per-pair rows in `pairs.csv` and the numbers in `summary.json`.
- **Coverage sidecars:** each `.jsonl` file gets a `.info.json` recording the time span, region and minimum magnitude the data covers (from the USGS query, or from CWA's own catalog metadata). Completeness is judged only where both inputs' coverage overlaps.
- **Raw responses** are kept under `out/raw/` so every result can be reproduced. `crosscheck parse` can re-read them; it skips the sidecar files.

Other commands:

```bash
crosscheck fetch cwa --product significant          # latest 16 felt reports (rapid, keyless via S3)
crosscheck fetch cwa --product significant --rest   # same via the REST API; needs CWA_API_KEY
crosscheck parse cwa saved/E-A0015-001.zip          # convert files you already saved
crosscheck cot out/cwa-2026.jsonl                   # CoT XML files for ATAK/WinTAK
crosscheck cot out/cwa-2026.jsonl --send localhost:8088   # also stream to a local OpenTAKServer
```

About `--send`: it streams over plain TCP, so use it only on a trusted local network. The behaviour is designed from OpenTAKServer 1.7.13's source code but has **not yet been tested against a running server**:
- the gateway announces itself first;
- events go out paced, about 30 s for 1,500 markers;
- the connection is closed cleanly.

The command reports whether the server confirmed it read everything. Even then, OpenTAKServer 1.7.13 can drop an event that arrives split across two network reads; pacing makes that unlikely, not impossible.

Method: [docs/METHOD.md](docs/METHOD.md). Sources and format traps: [docs/SOURCES.md](docs/SOURCES.md). Data attribution: [NOTICE.md](NOTICE.md). Reports and outputs built from CWA data carry CWA's required attribution automatically.

## Status

- Earthquake collectors (USGS, CWA reports and catalog), matcher, metrics, report and CoT file export are working, with tests on real saved data.
- The first real comparison (2015, 4 quakes) ran end to end. It is a smoke test, not a result; see docs/METHOD.md.
- Next: a full live comparison (1990–2026), a test against a real OpenTAKServer, a continuous collector for latency, then aircraft and ship pairs.
