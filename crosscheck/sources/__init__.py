"""One module per data source. Each turns that source's format into QuakeRecords."""

# Order of every bbox: (lon_min, lat_min, lon_max, lat_max).

# The region most CWA catalog files declare (CatalogInfo LongitudeRange
# 118.000-124.000, LatitudeRange 20.000-27.000). Five years (1996, 1997, 1999,
# 2003, 2012) declare 119-123E 21-26N instead; those declarations travel with
# the data as coverage metadata. Used as the comparison region only when an
# input carries no coverage of its own.
TAIWAN_BBOX = (118.0, 20.0, 124.0, 27.0)

# Default USGS download region: TAIWAN_BBOX plus 1 degree (about the 100 km
# matching distance) on every side, so quakes near the edge of CWA's region
# can still find their USGS partner. Completeness is still judged only where
# both datasets' declared regions overlap.
TAIWAN_FETCH_BBOX = (117.0, 19.0, 125.0, 28.0)
