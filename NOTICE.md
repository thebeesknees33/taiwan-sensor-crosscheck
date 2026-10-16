# Data attribution

## Central Weather Administration, Taiwan (CWA)

This project uses, and its test fixtures include, open data from:

交通部中央氣象署 (Central Weather Administration, Ministry of Transportation and Communications, Taiwan), 1990–2026:
- 顯著有感地震報告 Significant felt earthquake reports, E-A0015-001 / E-A0015-002
- 小區域有感地震報告 Small-area felt earthquake reports, E-A0016-001 / E-A0016-002
- 地震目錄 Earthquake catalog, E-A0073-001 / E-A0073-002

The Open Data is made available to the public under the Open Government Data License, User can make use of it when complying to the condition and obligation of its terms.

Open Government Data License, version 1.0: https://data.gov.tw/license

Under section 3.2 of that licence, the rights it grants are void if this attribution is left out of the data or its derivative works. The tool therefore adds it automatically when an output contains CWA data:
- comparison reports (`report.md`, `summary.json`, and an `ATTRIBUTION.txt` next to `pairs.csv`);
- the `.info.json` sidecar written next to each JSONL file;
- the remarks of every CWA marker in CoT/TAK output.

Keep it with anything you share.

## US Geological Survey (USGS)

Earthquake data from the USGS ComCat catalog (earthquake.usgs.gov). USGS-authored data is a US Government work, public domain in the US per USGS policy; this was not checked against a primary data-terms page. ComCat also carries solutions authored by other agencies. The test fixtures include events from `gcmt`, `iscgem`, `iscgemsup`, `ak`, `nn`, `pr`, `uw` and other networks, whose terms were not checked.

## Third-party recordings

Several test fixtures were recorded by other open-source projects. Each is a verbatim copy of a published USGS or CWA response, so arguably the project's own licence doesn't attach to it. Where the project has a licence, its text is kept next to the file anyway.

| Fixture | Recorded by | Licence |
|---|---|---|
| `tests/fixtures/cwa/rest-E-A0015-001-kuotunyu.json` | kuotunyu/taiwan-weather-mcp | MIT, `tests/fixtures/cwa/LICENSE-kuotunyu` |
| `tests/fixtures/cwa/rest-record-1150*-kiang.json` | kiang/opendata.cwa.gov.tw | MIT, `tests/fixtures/cwa/LICENSE-kiang` |
| `tests/fixtures/usgs/summary-all-day-2018.geojson` | exxamalte/python-geojson-client | Apache-2.0, `tests/fixtures/usgs/LICENSE-exxamalte` |
| `tests/fixtures/usgs/fdsn-2015-m6plus.geojson` | gist mikpan/63dfef22… | none declared |
| `tests/fixtures/usgs/fdsn-2018-*.geojson`, `fdsn-1904-1912-*.geojson` | usgs/libcomcat test cassettes | public domain in the US, CC0 1.0 worldwide |
