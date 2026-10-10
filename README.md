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

Collectors normalize each source into a common record. Optionally they emit Cursor-on-Target (CoT) XML so the data can be viewed in ATAK/WinTAK through a TAK server such as OpenTAKServer. Nothing goes over the network to a TAK server unless you explicitly ask it to.

## Scope

This is civilian measurement science and personal study. See [docs/SCOPE.md](docs/SCOPE.md) for what the project will and won't do.

## Status

Early setup. See the commit history.
