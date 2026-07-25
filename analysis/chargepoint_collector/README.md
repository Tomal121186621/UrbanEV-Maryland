# ChargePoint occupancy panel collector

`crawler_main.py` polls ChargePoint's public station-map service (the live feed behind its
driver app) on a ~10-minute loop, recording per-port status (in-use / available /
out-of-service) for Maryland stations to a timestamped SQLite database.
`LocalDatabaseCreation.ipynb` builds the database schema.

The May 2-26, 2026 collection (467 stations monitored, 455 usable; 1,755,160 snapshots,
~12-minute median cadence) is the observational panel behind the charging validation
(occupancy shape r = 0.78; weekday session-start profile r = 0.93). Stations were
crosswalked to the January-2026 AFDC registry by nearest match (631/632 within 600 m,
median 10.8 m).

The collected database is not distributed; validation scripts that consume it are in
`analysis/` (`validate_chargepoint_aggregate.py`, `validate_vs_chargepoint_v4.py`).
