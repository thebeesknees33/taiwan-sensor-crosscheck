"""One module per data source. Each turns that source's format into QuakeRecords."""

# Default comparison region: the region CWA's own catalog declares
# (CatalogInfo LongitudeRange 118.000-124.000, LatitudeRange 20.000-27.000).
# Order: (lon_min, lat_min, lon_max, lat_max).
TAIWAN_BBOX = (118.0, 20.0, 124.0, 27.0)
