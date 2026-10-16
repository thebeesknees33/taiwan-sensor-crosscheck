# Test fixture provenance

Every data file here is a genuine published response or file. All but two are byte-for-byte copies. The two exceptions (marked **decoded** below) are HTTP bodies decompressed from libcomcat's recorded test cassettes; their bytes are exactly the decompressed bodies. Nothing was hand-written or edited. Each file was re-downloaded and hash-checked during research on 2026-10-10.

The repository's `.gitattributes` marks this folder `-text`, so Git never converts line endings and the hashes below stay valid on every platform.

## USGS (US Geological Survey)

| File | Source | sha256 |
|---|---|---|
| `usgs/fdsn-2015-m6plus.geojson` | FDSN query `format=geojson&starttime=2015-01-01&endtime=2015-12-31&minmagnitude=6`, generated 2016-02-11 (api 1.1.1), saved in gist [mikpan/63dfef22…](https://gist.github.com/mikpan/63dfef2273d8077632784327867eeeac) revision 9a141b8a, file `earthquakes.geojson`. 156 events; 4 in the Taiwan region. | adab32f0ca8610e155461f963c0d4aced8e85eb1288f3ec469b320242260fe13 |
| `usgs/summary-all-day-2018.geojson` | Summary feed `all_day.geojson` snapshot, generated 2018-09-16 (api 1.5.8), from [exxamalte/python-geojson-client @ db369570](https://github.com/exxamalte/python-geojson-client/blob/db369570970aa6119894c81db140a65c8bb46b60/samples/usgs_all_earthquakes_past_day.json). That repository's Apache-2.0 licence, taken from the same commit, is `usgs/LICENSE-exxamalte`. | ae881917f2c0ea45ffe82e1e5d23fcf2f8d4731b17d859193f7fd1eb8e45a85b |
| `usgs/fdsn-2018-null-mag-negative-depth.geojson` | **Decoded** body of the single recorded response in [usgs/libcomcat @ 8d941dec, tests/libcomcat/cassettes/search_null.yaml](https://github.com/usgs/libcomcat/blob/8d941dec29f0b54c1b0a2cb5ed1f7710b7196b1a/tests/libcomcat/cassettes/search_null.yaml) (recorded 2021-11-09), from the cassette's base64+gzip body. | 8126d4751cb8569875800613b68d5948b142281ef0d4ab9e11648aa2985b8fa2 |
| `usgs/fdsn-1904-1912-null-depth.geojson` | **Decoded** body of interaction 4 in [usgs/libcomcat @ 8d941dec, tests/libcomcat/cassettes/dataframes_association.yaml](https://github.com/usgs/libcomcat/blob/8d941dec29f0b54c1b0a2cb5ed1f7710b7196b1a/tests/libcomcat/cassettes/dataframes_association.yaml), decoded the same way. | fbafb8d23648561a8181a87097d22f96619a5ff9823931c6efdbd51607b903a2 |

libcomcat is public domain in the US with a CC0 1.0 worldwide waiver. For the licence status of the data itself, see `NOTICE.md`.

## CWA (Central Weather Administration, Taiwan)

CWA data is licensed under the Open Government Data License, version 1.0. See [NOTICE.md](../../NOTICE.md) for the attribution statement.

| File | Source | sha256 |
|---|---|---|
| `cwa/E-A0015-001.zip` | `https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Earthquake/E-A0015-001.zip` (latest 16 significant felt reports, 2026-07-31 to 2026-10-06), fetched 2026-10-10 | 083382c11d6de39e2ba021f2a6f32ee63406cbb24995699292695af2fb21eeb3 |
| `cwa/E-A0016-001.zip` | `…/Earthquake/E-A0016-001.zip` (latest 16 small-area felt reports, to 2026-10-05) | cf12f19f451d564e4e8dcaa2a37f35145426a014a72406cc6902cbb5d20ac0d8 |
| `cwa/CWA-EQ115068-2026-1006-164108-OD_eng.xml` | English version of report 115068, extracted unchanged from `…/Earthquake/E-A0015-002.zip` | 09c7bc7a9e45b727f301d802074eda86331ef979a65844a47cc457fb093eb73c |
| `cwa/E-A0073-001.json` | `…/Earthquake/E-A0073-001.json` (catalog, 2026-01-01 to 2026-10-01, 1507 events) | 615063d1e3c0e8cfc9d3871b8b8520b6c6908417e1b115c5e212370087195486 |
| `cwa/CWA-EQ-Catalog-2015.xml` | Extracted unchanged from `…/Earthquake/E-A0073-002.zip` (yearly catalogs 1990–2025) | 4334d7421c4cc1bd2bde356e45b26e448153443fc193c6f1b2dfd68df1b158b7 |
| `cwa/rest-E-A0015-001-kuotunyu.json` | A real REST response (`E-A0015-001`, `limit=5`, July 2026) recorded by [kuotunyu/taiwan-weather-mcp, tests/fixtures/e_a0015_001.json](https://raw.githubusercontent.com/kuotunyu/taiwan-weather-mcp/main/tests/fixtures/e_a0015_001.json). Re-serialized by that project with Python `json.dumps(indent=2)`, so values are intact but whitespace differs from the wire. Repository MIT licence: `cwa/LICENSE-kuotunyu`. | 01f29256736d8dce6d31871162a510da6545fc4e2af36362870823b7a1b0341e |
| `cwa/rest-record-115031-kiang.json` | One REST record in the **old** time format (`"2026-04-05 01:14:58"`, no offset), archived by [kiang/opendata.cwa.gov.tw, docs/cases/115/115031.json](https://raw.githubusercontent.com/kiang/opendata.cwa.gov.tw/master/docs/cases/115/115031.json). Re-serialized by PHP `json_encode`, which drops `.0` from whole numbers. Repository MIT licence: `cwa/LICENSE-kiang`. | 59a5e5f4715bd5b906868b0955c260aa6a1ed16d15d943f6b8ca90c41f4c8a09 |
| `cwa/rest-record-115032-kiang.json` | The next record, the first in the **new** format (`"2026-04-05T05:23:59+08:00"`), same archive. | 5e24761c56dcb01eacdbdeebdb4912556ae9645f401797ad0f0557ae5f7eb98c |

## Hand-written and synthetic inputs

- Parser tests parse only the real files above.
- Error-path tests use minimal hand-written inputs: an invalid REST body, an unsupported product file, a padded time string, a `file.csv` index inside a test zip.
- Fetch tests use a fake HTTP session that serves the real files (or builds `/count` replies).
- Matching, statistics and CoT tests (`test_match.py`, `test_compare.py`, `test_cot.py`) use small synthetic records built in `conftest.rec()`. They check the algorithms, not real-world accuracy.
- The end-to-end comparison uses only real data.
