# Data sources

What each source publishes, how to get it, and the format traps found in real data. Confidence labels:
- **verified**: seen in official docs or a real saved response;
- **secondhand**: seen only in third-party code or docs, or in search-engine excerpts;
- **inference**: generalized from a limited sample, as stated.

Research date: 2026-10-10. The endpoints below were blocked from the research sandbox, so everything was checked against real saved responses (see `tests/fixtures/PROVENANCE.md`). The one exception is CWA's S3 bucket, which was reachable.

## USGS ComCat (earthquake.usgs.gov)

**Access:** `GET https://earthquake.usgs.gov/fdsnws/event/1/query`, with `/count` taking the same parameters.

| Parameters | Confidence |
|---|---|
| `format=geojson`, `starttime`, `endtime`, `minmagnitude`, `eventtype=earthquake`, `orderby=time-asc`, `limit`, `offset` | verified in real recorded requests |
| `minlatitude`, `maxlatitude`, `minlongitude` | verified in a USGS FDSN WADL from 2013, which lists `minlongitude` twice and omits `maxlongitude` |
| `maxlongitude` | secondhand (FDSN standard, libcomcat code) |
| UTC as the default time zone | secondhand |

`/count` returns `{"count": N, "maxAllowed": 20000}` (verified). Larger windows are split automatically.

The default download box is 117–125°E, 19–28°N: CWA's catalog region plus 1° on every side, so quakes near its edge can still find partners. The query (time span, box, minimum magnitude) is saved as the file's coverage.

**Politeness:** USGS announced rate limiting (HTTP 429) in 2022 and caches responses for 60 s (secondhand). The client sends a descriptive User-Agent, asks for gzip, waits at least 1 s between requests, retries timeouts and 429/5xx with backoff, honours `Retry-After` (seconds or HTTP date), and stops rather than retry early if asked to wait more than 5 minutes.

**Format (verified on 1,682 real features from 2016–2025):**
- `geometry.coordinates` = `[lon, lat, depth_km]`. Depth can be negative (above the datum) or `null`.
- `properties.time` and `updated` are signed epoch **milliseconds** UTC.
- `mag` and `magType` can be `null`. `magType` case varies (`mww`, `Mfa`), so it's stored lower-cased plus raw.
- `ids`, `sources` and `types` are comma lists with leading and trailing commas.
- `place` changes over time, and **Taiwan-region events can be labelled "SW of Yonakuni, Japan"**. Select by coordinates, never by place text.
- `updated` is the *last* update, not first publication. Latency has to come from our own `retrieved_at`.
- `tz` is usually `null`; ignore it.

**Independence from CWA:**
- **Endpoints:** in 2021, ComCat's `/contributors` and `/catalogs` endpoints listed no Taiwan network (verified).
- **Directory:** ComCat's contributor directory (2020 website source) does list `tap` ("Central Weather Bureau, Taipei, Taiwan", CWA's former name) and `tato` (Academia Sinica). What they contribute is not documented.
- **Event authors:** the 2015 Taiwan M6+ events checked were NEIC (`us`) solutions.
- **Station data:** NEIC phase data has included some picks and amplitudes from Taiwan's BATS (`TW`) stations, run by Academia Sinica, not CWA (verified for two non-Taiwan events). Whether NEIC solutions for Taiwan events use CWA (`T5`) data is **unknown**.

So the two catalogs are mostly, but not provably fully, independent.

**Coverage caveat:** USGS says it may not rapidly locate non-US quakes below M5, and that ones below about M4.5 can be hard to locate (verified, 2020 site text). Expect many small CWA events to have no USGS partner.

**Licence:** USGS-authored data is a US Government work, public domain in the US per USGS policy (not checked against a primary data-terms page). ComCat also carries solutions authored by other agencies (e.g. `gcmt`, `iscgem`, regional networks), whose terms were not checked.

## CWA (Central Weather Administration, Taiwan)

**Licence:** Open Government Data License v1.0. Attribution is required (see `NOTICE.md`). The tool adds it to the reports, summaries, JSONL sidecars and TAK markers it generates from CWA data.

### Felt earthquake reports (rapid)

| Dataset | Content |
|---|---|
| E-A0015-001 / -002 | Significant felt reports (Chinese / English) |
| E-A0016-001 / -002 | Small-area felt reports (Chinese / English) |

**Access, no key:** `https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Earthquake/E-A0015-001.zip` (and `E-A0016-001.zip`). Each holds the **latest 16 reports** as XML (verified). Values match the REST API for the same report (verified on one report). In a single observation, the zip updated within about a minute of a report being issued.

**Access, with key:** `https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0015-001?Authorization=<key>&format=JSON` (secondhand, from several third-party clients; `limit` also seen). Keys are free from opendata.cwa.gov.tw. Set `CWA_API_KEY`. The key is removed from saved metadata and from error messages.

**Format traps:**
- `OriginTime` is Taiwan local time, **whole seconds** (verified). Old-style REST records have `"YYYY-MM-DD HH:MM:SS"` with **no offset**, newer ones `+08:00`. In a third-party archive of real REST responses, the switch falls between report 115031 (2026-04-05 01:14 local) and 115032 (05:23 local). The parser recognizes both formats from the text itself.
- Magnitude is local magnitude **ML** (Chinese label 芮氏規模, English `ML`) (verified).
- All 32 small-area reports on S3 in October 2026 (16 Chinese, 16 English) had `EarthquakeNo` 115000 (verified), so it can't be an id. We use `EarthquakeNo` + UTC origin time. That small-area numbers are always `<year>000` is an **inference** from one year of files. The parser uses it to tell significant from small-area reports when the dataset id isn't known.
- Report precision: lat/lon 0.01° (about 1.1 km), depth 0.1 km, ML 0.1 (verified).
- Reports are rapid results. CWA's own reviewed catalog differs from them by up to 11.5 km in epicenter and 29.6 km in depth (2026 sample of 15 reports).
- XML files start with a UTF-8 BOM. `ShakemapImageURI` is absent from small-area reports, and `ReportRemark` from English ones (verified).
- Some published third-party clients use wrong field names (e.g. `EpiCenter`). Field names here come from real responses only.

### Earthquake catalog (reviewed, M≥3)

| File | Content |
|---|---|
| `Earthquake/E-A0073-001.json` | Current year so far (2026: 1,507 events to 2026-10-01) |
| `Earthquake/E-A0073-002.zip` | One XML per year, `CWA-EQ-Catalog-1990.xml` … `-2025.xml` (73,729 events) |

Both are on the same public S3 bucket, no key needed (verified).

**Fields:** `OriginTime` (+08:00, whole seconds), `EpicenterLatitude`/`Longitude` (0.001°), `FocalDepth`, `LocalMagnitude`, `StationNumber`, `PhaseNumber`, `gap` (度, degrees), `rms` (秒, seconds), `erh`/`erz` (公里, km), `Quality` (A–D), `ReviewStatus`. The meanings of the Quality grades and ReviewStatus codes are **unverified**.

**Traps (verified on the full 1990–2026 set):**
- All values are strings, and every yearly XML `LocalMagnitude` value has a leading space.
- **Catalog years are UTC years.** Each file's `CatalogInfo` runs from `<year>-01-01T08:00+08:00` to the next. A finished year reaches the zip some weeks into the next year: the 2023 file is dated 2024-01-26, 2024 is 2025-02-12, 2025 is 2026-01-15. For last year the tool reads both files.
- **Declared regions differ by year.** 31 files declare 118–124°E, 20–27°N; the 1996, 1997, 1999, 2003 and 2012 files declare 119–123°E, 21–26°N. The tool uses each file's own declaration as its coverage.
- **A few events lie outside the declared region:** 25 of 73,729 (1990–2025), 19 of them east of 124°E. They include 14 of the 170 events of ML ≥ 6, so M6+ comparisons should widen the USGS download beyond the default.

## Planned later

Aircraft (OpenSky, adsb.lol), ships (AIS feeds, Sentinel imagery) and ocean/weather data. They will be added after the earthquake method is settled.
