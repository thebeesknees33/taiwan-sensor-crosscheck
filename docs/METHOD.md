# Comparison method

## 1. Normalize

Each source becomes `QuakeRecord`s: UTC origin time, lat/lon (WGS84), depth (km, positive down), magnitude and magnitude type (lower-cased, raw kept), plus source-specific extras. Values keep the precision the source published.

## 2. Match: which records are the same quake?

**Gate.** A pair is possible only if |origin-time difference| ≤ 16 s **and** epicentral distance ≤ 100 km. These are the values USGS itself uses to associate solutions from different networks: `TIME_DIFF_MILLISECONDS = 16 * 1000` and `LOCATION_DIFF_KILOMETER = 100` in PDL's `DefaultAssociator.java`, and the `associate()` defaults in USGS libcomcat (verified in source). Both windows are configurable. `--sweep` shows how the result changes for 16/30/60/120 s × 50/100/150 km, because USGS's own tests show 16 s can miss real pairs.

**Magnitude is not a gate.** CWA reports ML while USGS reports mb, Mww and others. Taiwan ML reads about 0.2 above Mw for shallow quakes and up to about 0.5 above it for deep ones (Guan, Kuo-Chen & Sun 2020; Wu, Allen & Wu 2005; both secondhand via abstracts). libcomcat's default 0.5 magnitude limit could therefore throw away true pairs.

**One-to-one.** Each record pairs with at most one record from the other catalog, a rule shared by catalog-merging tools. Within each cluster of mutually reachable records, the assignment first maximizes the number of pairs, then minimizes the total of `cost = sqrt((dt/16 s)² + (dist/100 km)²)`, the normalized time-distance form PDL uses to break ties (scipy `linear_sum_assignment`). This avoids a greedy match stealing the only partner of another quake.

**Ambiguity.** A pair is flagged when another candidate for either record has a cost within 1.5× of the chosen one. This threshold is our choice, not a published standard. Summaries are reported for all pairs and for unambiguous pairs only.

## 3. Measure

For each pair, signed **A minus B** (default A = CWA, B = USGS):

| Quantity | Notes |
|---|---|
| Origin time (s) | |
| Epicenter distance (km) | great circle on a 6371.0088 km sphere, accurate to about 0.5% |
| Offset direction | azimuth from the B epicenter to the A epicenter, plus east/north components; summarized as a mean offset vector (the form used by Hjörleifsdóttir et al. 2016 for USGS vs Mexican catalogs) |
| Depth (km) | positive = A deeper |
| Magnitude | **only grouped by type pair** (e.g. `ml-mww`), never pooled across scales |

Each quantity gets n, mean, median, standard deviation, MAD (median absolute deviation) and range. Results are also split by A's depth (shallow ≤ 35 km vs deep), the split Guan et al. used for Taiwan ML.

**Precision floor.** CWA reports give lat/lon to 0.01° (±0.55 km), depth to 0.1 km and ML to 0.1. Differences that small are rounding, not disagreement.

## 4. Completeness

Inside the overlap window (the time span both inputs cover, within the bbox, default 118–124°E 20–27°N), we count how many events above a cutoff magnitude found a partner, in each direction. The cutoff is applied to each catalog's own scale. Unmatched events are listed, not hidden.

**Trap: inputs downloaded with a magnitude limit.** If one input was fetched with, say, `minmagnitude=6`, a quake that the other catalog rates M6.1 but this one rates M5.9 will look "missed". The report warns when an input's smallest magnitude sits within 0.5 of the cutoff.

## 5. Latency (planned)

ComCat's `updated` field is the last update, not first publication (verified), so latency must come from our own polling: `retrieved_at` minus origin time. This needs a collector that runs continuously. It is not part of a one-off comparison.

## First result (2015, real data, n = 4)

CWA's 2015 catalog vs a saved USGS query of 2015 M6+ events. These are the only real USGS Taiwan-region data reachable during development; the full comparison needs a live run (see README).

| Quantity | median | range |
|---|---:|---:|
| Origin time CWA−USGS (s) | −0.70 | −2.38 to +0.56 |
| Epicenter distance (km) | 9.46 | 3.84 to 23.76 |
| Depth CWA−USGS (km) | +1.00 | −2.20 to +4.90 |
| ML − Mww | +0.05 | −0.10 to +0.20 |

Mean offset: CWA epicenters 9.7 km toward 147° (south-southeast) of USGS. With four offshore-eastern events this is an anecdote, not a finding. The point of the run is that the pipeline works end to end on genuine data.

## Sources

- USGS PDL `DefaultAssociator.java`: https://raw.githubusercontent.com/usgs/pdl/master/src/main/java/gov/usgs/earthquake/indexer/DefaultAssociator.java (verified)
- USGS libcomcat `associate()`: https://raw.githubusercontent.com/usgs/libcomcat/master/libcomcat/dataframes.py (verified)
- Guan, Kuo-Chen & Sun (2020), TAO 31(4):479–486, doi:10.3319/TAO.2020.06.16.01 (secondhand, abstract)
- Wu, Allen & Wu (2005), BSSA 95(6):2517–2524, doi:10.1785/0120050043 (secondhand, abstract)
- Hjörleifsdóttir, Singh & Husker (2016), Geofísica Internacional 55(1) (secondhand, abstract)
