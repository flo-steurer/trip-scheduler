# Removing the 2026 World Cup integration

Run this only after all World Cup markets are settled.

1. Set `WORLD_CUP_SYNC_ENABLED=false` and redeploy to stop new synchronization.
2. Remove the `world-cup-sync` Compose service, football-data.org settings, the `world_cup` app from `INSTALLED_APPS`, and the three scheduler integration points (results payload, new-trip materialization, trade lock).
3. Add and apply a final migration that drops `WorldCupMarket` and `WorldCupFixture`.

The linked generic `scheduler_market` and `scheduler_markettrade` rows must not be deleted. They are the preserved historical Beermarket records.
