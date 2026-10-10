# Data sources

What each source publishes, how to get it, and the format traps found in real data. Confidence labels:
- **verified**: seen in official docs or a real saved response;
- **secondhand**: seen only in third-party code or docs, or in search-engine excerpts;
- **unverified**: not confirmed.

Research date: 2026-10-10. The endpoints below were blocked from the research sandbox, so everything was checked against real saved responses (see `tests/fixtures/PROVENANCE.md`). The one exception is CWA's S3 bucket, which was reachable.

## USGS ComCat (earthquake.usgs.gov)

**Access:** `GET https://earthquake.usgs.gov/fdsnws/event/1/query` with `format=geojson`, `starttime`/`endtime` (UTC), `minlatitude`/`maxlatitude`/`minlongitude`/`maxlongitude`, optional `minmagnitude`, `eventtype=earthquake`, `orderby=time-asc`, `limit` (verified from real recorded requests). `/count` with the same parameters returns `{"count": N, "maxAllowed": 20000}` (verified). Larger windows are split automatically.

**Politeness:** USGS announced rate limiting (HTTP 429) in 2022 and caches responses for 60 s (secondhand). The client sends a descriptive User-Agent, asks for gzip, waits at least 1 s between requests and backs off on 429/503.

**Format (verified on 1,682 real features from 2016–2025):**
- `geometry.coordinates` = `[lon, lat, depth_km]`. Depth can be negative (above the datum) or `null`.
- `properties.time` and `updated` are signed epoch **milliseconds** UTC.
- `mag` and `magType` can be `null`. `magType` case varies (`mww`, `Mi`, `Ml`), so it's stored lower-cased plus raw.
- `ids`, `sources` and `types` are comma lists with leading and trailing commas.
- `place` changes over time, and **Taiwan-region events can be labelled "SW of Yonakuni, Japan"**. Select by coordinates, never by place text.
- `updated` is the *last* update, not first publication. Latency has to come from our own `retrieved_at`.
- `tz` is usually `null`; ignore it.

**Independence from CWA:** as of 2021 ComCat had no Taiwan contributor network (verified). The Taiwan M6+ events checked were NEIC (`us`) solutions. NEIC phase data has included some picks and amplitudes from Taiwan's BATS (`TW`) stations, run by Academia Sinica, not CWA (verified for two non-Taiwan events). Whether NEIC solutions for Taiwan events use CWA (`T5`) data is **unknown**. So the two catalogs are mostly, but not provably fully, independent.

**Coverage caveat:** USGS says it may not rapidly locate non-US quakes below M5, and that ones below about M4.5 can be hard to locate (verified, 2020 site text). Expect many small CWA events to have no USGS partner.

## CWA (Central Weather Administration, Taiwan)

**Licence:** Open Government Data License v1.0. Attribution is required (see `NOTICE.md`).

### Felt earthquake reports (rapid)

| Dataset | Content |
|---|---|
| E-A0015-001 / -002 | Significant felt reports (Chinese / English) |
| E-A0016-001 / -002 | Small-area felt reports (Chinese / English) |

**Access, no key:** `https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Earthquake/E-A0015-001.zip` (and `E-A0016-001.zip`), each the **latest 16 reports** as XML (verified; the zip updated within about a minute of a report). Same values as the REST API for the same report (verified on one report).

**Access, with key:** `https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0015-001?Authorization=<key>&format=JSON` (secondhand, from several third-party clients; `limit` also seen). Keys are free from opendata.cwa.gov.tw. Set `CWA_API_KEY`. The key is redacted from saved metadata.

**Format traps (verified):**
- `OriginTime` is Taiwan local time. REST records before 2026-04-05 used `"YYYY-MM-DD HH:MM:SS"` with **no offset**; later ones use `+08:00`.
- Magnitude is local magnitude **ML** (Chinese label 芮氏規模, English `ML`).
- All small-area reports in a year share `EarthquakeNo` `<year>000`, so it can't be an id. We use `EarthquakeNo` + UTC origin time.
- Report precision: lat/lon 0.01° (about 1.1 km), depth 0.1 km, ML 0.1.
- Reports are rapid results. CWA's own reviewed catalog differs from them by up to 11.5 km in epicenter and 29.6 km in depth (2026 sample of 15 reports).
- XML files start with a UTF-8 BOM. `ShakemapImageURI` is absent from small-area reports, and `ReportRemark` from English ones.
- Some published third-party clients use wrong field names (e.g. `EpiCenter`). Field names here come from real responses only.

### Earthquake catalog (reviewed, M≥3)

| File | Content |
|---|---|
| `Earthquake/E-A0073-001.json` | Current year so far (2026: 1,507 events to 2026-10-01) |
| `Earthquake/E-A0073-002.zip` | One XML per year, `CWA-EQ-Catalog-1990.xml` … `-2025.xml` |

Both are on the same public S3 bucket, no key needed (verified). Fields: `OriginTime` (+08:00), `EpicenterLatitude`/`Longitude` (0.001°), `FocalDepth`, `LocalMagnitude`, `StationNumber`, `PhaseNumber`, `gap` (度, degrees), `rms` (秒, seconds), `erh`/`erz` (公里, km), `Quality` (A–D), `ReviewStatus`. Traps: all values are strings, and every yearly XML `LocalMagnitude` value has a leading space. The catalog region is 118–124°E, 20–27°N, which this project uses as its default comparison box. The meanings of the Quality grades and ReviewStatus codes are **unverified**.

## Planned later

Aircraft (OpenSky, adsb.lol), ships (AIS feeds, Sentinel imagery) and ocean/weather data. They will be added after the earthquake method is settled.
