## Problem
162216 asset page showed 688525 weight at 256.51% (normal should be < 1%). 87 rows with weight > 100 were found in the database.

## Root Cause
1. _sync_asset_inventory hardcoded report_date to 2025-12-31, all holdings shared same date
2. batch_upsert only INSERT/UPDATES, never DELETES old mappings
3. No validation on source pct values, bad data entered directly

## Fix (Code)
- Weight validation: reject pct > 100% with warning log
- Date fix: derive real report_date from quarter field (e.g. 2026Q2 -> 2026-06-30)
- Cleanup before upsert: DELETE existing mappings for funds being refreshed

## Fix (Data - already executed on server)
- Deleted 87 rows with weight > 100
- Deleted 104 rows with weight IS NULL
- Fixed 21145 report_date values from 2025-12-31/2000-01-01 to 2026-06-30
