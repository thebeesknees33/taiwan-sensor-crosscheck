# Comparison method

## 1. Normalize

Each source becomes `QuakeRecord`s: UTC origin time, lat/lon (WGS84), depth (km, positive down), magnitude and magnitude type (lower-cased, raw kept), plus source-specific extras. Values keep the precision the source published.

Each output file also gets a sidecar, `<name>.info.json`, recording the **coverage** the data declares: the time span, region and minimum magnitude it promises to include. A USGS download records its query. A CWA catalog file records its own `CatalogInfo`. Felt reports declare nothing (they are just "the latest 16").

## 2. Match: which records are the same quake?

**Gate.** A pair is possible only if |origin-time difference| ≤ 16 s **and** great-circle epicentral distance ≤ 100 km. These values come from USGS's own association code: `TIME_DIFF_MILLISECONDS = 16 * 1000` and `LOCATION_DIFF_KILOMETER = 100` in PDL's `DefaultAssociator.java`, and the `associate()` defaults in libcomcat (verified in source). PDL applies the 100 km as a lat/lon box (±0.9° latitude, ±0.9°/cos(lat) longitude), so its corners reach about 141 km. We apply it as a circle, which is stricter at the corners. Both windows are configurable.

**Why `--sweep`.** Whether real CWA/USGS pairs ever exceed 16 s or 100 km is an empirical question, and `--sweep` measures it: it repeats the matching for 16/30/60/120 s × 50/100/150 km. (libcomcat's own tests only show its 16 s default rejecting a hand-made input about 62 s from the nearest ComCat event; that is not evidence about real pairs.)

**Magnitude is not a gate.** CWA reports ML while USGS reports mb, Mww and others. Guan, Kuo-Chen & Sun (2020) report Taiwan ML about 0.2 above Mw for shallow quakes and, for deep quakes with ML > 6, around 0.5 above it. Wu, Allen & Wu (2005) report Taiwan ML reading high relative to Mw. (Both secondhand, via abstracts.) libcomcat's default 0.5 magnitude limit could therefore throw away true pairs.

**One-to-one.** Each record pairs with at most one record from the other catalog, a rule shared by catalog-merging tools. Within each cluster of mutually reachable records, the assignment first maximizes the number of pairs. It then minimizes the total of a PDL-style normalized cost, `sqrt((dt/16 s)² + (dist/100 km)²)`, using scipy's `linear_sum_assignment`. PDL itself breaks ties with normalized lat/lon degrees and time, chosen greedily per product. Global assignment avoids a greedy match stealing the only partner of another quake.

**Ambiguity.** A pair is flagged when another candidate for either record has a cost within 1.5× of the chosen one. This threshold is our choice, not a published standard. Summaries are reported for all pairs and for unambiguous pairs only.

Times are compared in exact integer microseconds, so the gate edges are inclusive as documented.

## 3. Measure

For each pair, signed **A minus B** (default A = CWA, B = USGS):

| Quantity | Notes |
|---|---|
| Origin time (s) | see the precision floor below |
| Epicenter distance (km) | great circle on a 6371.0088 km sphere, accurate to about 0.5% |
| Offset direction | azimuth from the B epicenter to the A epicenter, plus east/north components, summarized as a mean offset vector (the form used by Hjörleifsdóttir et al. 2016 for USGS vs Mexican catalogs) |
| Depth (km) | positive = A deeper |
| Magnitude | **only grouped by type pair** (e.g. `ml-mww`), never pooled across scales |

Each quantity gets n, mean, median, standard deviation, MAD (median absolute deviation) and range. Results are also split by A's depth (shallow ≤ 35 km vs deep), the split Guan et al. used. When there are 30 pairs or fewer, the report lists every pair.

**Precision floor.** Differences below the published precision are rounding, not disagreement:

- CWA reports give lat/lon to 0.01° (±0.55 km), depth to 0.1 km and ML to 0.1. The catalog gives lat/lon to 0.001°.
- **CWA origin times are whole seconds** in every report and catalog file checked (0 of 73,729 catalog times have a fractional second). Time differences under about 1 s cannot be resolved. If CWA truncates rather than rounds (not known), CWA−USGS carries a constant offset of about −0.5 s that averaging will not remove.

The report adds this note automatically when one side's times are all whole seconds.

## 4. Completeness

Did each catalog see the quakes the other one saw? This is judged only inside the **overlap of the two inputs' declared coverage**: the intersection of their time spans and regions.

- CWA's catalog declares 118–124°E, 20–27°N in 31 of 36 yearly files, but 119–123°E, 21–26°N for 1996, 1997, 1999, 2003 and 2012. Each year's own region is used.
- The default USGS download box is CWA's region plus 1° on every side (117–125°E, 19–28°N). Quakes near the edge of CWA's region can then still find a USGS partner within 100 km.
- `--start`, `--end` and `--bbox` can narrow the overlap further.
- If an input has no recorded coverage, its span is inferred from its first and last events, and the report says so. Misses near the ends of an inferred span are not counted.

Counting rules:

- A matched pair counts on both sides when either member is inside the overlap, so a sub-second edge cannot split a match.
- Unmatched events inside the overlap are listed. Unmatched events outside it are counted separately as not judged, never silently dropped.
- `--min-mag` applies to each catalog's own magnitude scale.

**Magnitude floors.** If one input has nothing below magnitude *f*, quakes the other catalog rates below about *f* + 0.5 may have no partner for that reason alone (the scale margin above). This happens when the input was downloaded with a magnitude limit, or when *f* is simply its detection threshold. The report warns whenever the cutoff (or, with no cutoff, the other catalog's smallest magnitude) is below *f* + 0.5, and suggests a `--min-mag` that avoids it. *f* is the declared floor when known (the USGS query's `minmagnitude`, or CWA's `MagnitudeRange` of 3.00–9.00). Otherwise it is the smallest magnitude actually present.

## 5. Latency (planned)

ComCat's `updated` field is the last update, not first publication (verified), so latency must come from our own polling: `retrieved_at` minus origin time. This needs a collector that runs continuously. It is not part of a one-off comparison.

## First result (2015, real data, n = 4)

CWA's 2015 catalog vs a saved USGS query of 2015 M6+ events (global, ending 2015-12-31T00:00Z). These are the only real USGS Taiwan-region data reachable during development; the full comparison needs a live run (see README).

| CWA | USGS | dt (s) | distance (km) | toward (°) | depth diff (km) | ML vs Mww |
|---|---|---:|---:|---:|---:|---|
| 2015-02-13 20:06:32 (Taitung, offshore) | usb000tp6y | −0.33 | 3.84 | 307 | −2.2 | 6.3 vs 6.2 |
| 2015-04-20 01:42:56 | us200027ps | −2.38 | 23.76 | 148 | +1.6 | 6.4 vs 6.4 |
| 2015-04-20 11:45:14 | us200027rt | +0.56 | 7.82 | 135 | +4.9 | 6.2 vs 6.0 |
| 2015-04-20 11:59:59 | us200027ru | −1.07 | 11.10 | 147 | +0.4 | 6.0 vs 6.1 |

What this does and doesn't show:

- **It is a smoke test of the pipeline, not a finding.**
- **Three of the four pairs are one sequence.** Their CWA epicenters are 6.9–9.8 km apart, off eastern Taiwan on 2015-04-20. So the mean offset of 9.7 km toward 147° is essentially that one cluster's offset. The only independent pair (Taitung, about 185 km away) points the opposite way (307°).
- **The magnitude row is selected on the USGS magnitude.** The USGS file only holds quakes USGS rated M6.0 or more. CWA's other ML ≥ 6 quake that year (2015-03-23, ML 6.2, 38.4 km deep) has no partner, presumably because USGS rated it below 6. It is also the kind of deep ML > 6 event where Guan et al. expect ML to read about 0.5 high, so leaving it out biases ML−Mww low by selection. The tool flags this with its magnitude-floor warning and suggests `--min-mag 6.5`.
- **Two of the four time differences are smaller than CWA's 1-second resolution**, so the median of −0.70 s cannot be interpreted.

## Sources

- USGS PDL `DefaultAssociator.java`: https://raw.githubusercontent.com/usgs/pdl/master/src/main/java/gov/usgs/earthquake/indexer/DefaultAssociator.java (verified)
- USGS libcomcat `associate()` and its tests: https://raw.githubusercontent.com/usgs/libcomcat/master/libcomcat/dataframes.py, `tests/libcomcat/dataframes_test.py` (verified)
- Guan, Kuo-Chen & Sun (2020), TAO 31(4):479–486, doi:10.3319/TAO.2020.06.16.01 (secondhand, abstract)
- Wu, Allen & Wu (2005), BSSA 95(6):2517–2524, doi:10.1785/0120050043 (secondhand, abstract)
- Hjörleifsdóttir, Singh & Husker (2016), Geofísica Internacional 55(1) (secondhand, abstract)
