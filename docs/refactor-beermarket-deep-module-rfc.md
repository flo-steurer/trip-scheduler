## Problem

The current Beermarket implementation has the right product behavior, but the ownership of that behavior is too shallow. One market trade currently requires callers to understand request validation, participant lookup, chip amount parsing, row locking, World Cup tradeability, dynamic seed liquidity, LMSR pricing, balance mutation, chip ledger events, `MarketTrade` creation, and result recomputation.

The coupled modules are:

- `scheduler.views.market_trade_api`, which owns the trade transaction orchestration.
- `scheduler.models.Market`, which owns pricing helpers, seed liquidity, and settlement.
- `scheduler.services.trip_results`, which rebuilds market odds, positions, payouts, and World Cup payloads.
- `scheduler.services.market_performance`, which separately interprets settled market trades.
- `world_cup.services`, which settles automatic markets through `Market.resolve`.
- `scheduler.admin.MarketAdmin`, which also resolves manual markets through `Market.resolve`.

This creates integration risk in the seams between pricing, ledger accounting, and read projection. The riskiest part is not LMSR math by itself; it is callers needing to remember every invariant around the math. A missing ledger event, a new trade path that forgets `shares_millis`, or a tradeability check in only one caller would corrupt money-like state.

The legacy fixed-chip implementation should not be restored or modeled as a supported market type. Current behavior is the polymarket-style share market: trades spend chip millis, receive LMSR-priced shares, store `cost_millis` and `shares_millis`, and settle by paying winning shares. The only legacy tolerance that should remain is read-side compatibility for historical rows where `cost_millis` or `shares_millis` is missing.

## Proposed Interface

Create a deep Beermarket module, likely `scheduler/beermarket.py`, with a small public boundary:

```python
@dataclass(frozen=True)
class TradeReceipt:
    trip: Trip
    participant: Participant
    trade: MarketTrade
    cost_millis: int
    shares_millis: int
    entry_odds: int
    balance_after_millis: int

    @property
    def activity_action(self) -> str:
        return f"market_trade_bought_{self.trade.outcome}_{self.cost_millis}"


class BeermarketError(Exception):
    public_message: str


def place_trade(
    *,
    trip_public_id: UUID,
    market_id: int,
    participant_name: object,
    outcome: object,
    chips: object,
) -> TradeReceipt:
    ...


def settle_market(*, market_id: int, outcome: str, allow_automatic: bool = True) -> int:
    ...


def project_trip_markets(*, trip: Trip) -> list[dict]:
    ...


def market_performance(*, trip: Trip) -> dict:
    ...
```

The first implementation milestone should migrate `market_trade_api` to `place_trade`. That gives the largest immediate safety gain while keeping blast radius controlled. Settlement and projection can then move behind the same module in follow-up commits without changing user-visible behavior.

Usage example for the trade endpoint:

```python
@require_POST
def market_trade_api(request, public_id, market_id):
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Expected a JSON request body."}, status=400)

    try:
        receipt = place_trade(
            trip_public_id=public_id,
            market_id=market_id,
            participant_name=body.get("name"),
            outcome=body.get("outcome"),
            chips=body.get("chips"),
        )
    except BeermarketError as error:
        return JsonResponse({"error": error.public_message}, status=400)

    _activity(request, receipt.participant, receipt.activity_action)
    return _results_response(
        receipt.trip,
        participant=_participant_payload(receipt.participant),
    )
```

Complexity hidden by `place_trade`:

- Participant lookup and name validation for the trip.
- Outcome validation against `Market.Outcome`.
- Chip input parsing to `cost_millis`, including bool rejection and the current `0.001` chip minimum.
- Atomic transaction ownership and row locking for market and participant.
- Rejection for resolved markets.
- Rejection for non-tradeable World Cup markets through the local fixture link.
- First-trade seed liquidity refresh from the current trip chip economy.
- LMSR price snapshot, entry odds, and share calculation.
- Participant chip deduction.
- `ChipBalanceEvent(reason=MARKET_TRADE)` creation.
- `MarketTrade` creation with required `cost_millis` and `shares_millis`.

Complexity hidden by later `settle_market`, `project_trip_markets`, and `market_performance` migrations:

- Settlement payout aggregation and `MARKET_PAYOUT` ledger events.
- Beer Karma award for winning traders.
- Odds history reconstruction.
- Position aggregation by participant.
- Mark-to-market value, unrealized P/L, entry odds, and settled payout fields.
- World Cup metadata projection.
- Settled-market performance ranking.
- Read-only fallback for old rows:

```python
cost_millis = trade.cost_millis if trade.cost_millis is not None else trade.chips * Market.SHARE_SCALE
shares_millis = trade.shares_millis if trade.shares_millis is not None else trade.chips * Market.SHARE_SCALE
```

That fallback must not be used for new writes.

## Dependency Strategy

Dependency category: **Local-substitutable**.

The module depends on Django ORM models, database transactions, row locks, and local app tables such as `WorldCupMarket` and `WorldCupFixture`. These can be tested with Django's normal local test database. No remote services or external mocks are needed for core Beermarket behavior.

The module may read local World Cup fixture state to decide tradeability, but it should not call `world_cup.provider` or trigger fixture sync. Football-data.org remains outside this boundary.

Keep the module intentionally opinionated around the current polymarket-style market model:

- New trades always persist `cost_millis`.
- New trades always persist `shares_millis`.
- LMSR pricing remains the only write path.
- The old fixed-chip behavior is not a market type, strategy, adapter, or extension point.

## Testing Strategy

New boundary tests to write:

- `place_trade` creates a participant by display name, deducts chip millis, creates one `MARKET_TRADE` ledger event, creates a `MarketTrade`, and returns a receipt with the updated balance.
- `place_trade` rejects invalid names, invalid outcomes, boolean chip values, malformed chip values, amounts below `0.001`, overspending, resolved markets, and non-tradeable World Cup markets with the same public messages the endpoint returns today.
- `place_trade` raises first-trade seed liquidity when the current trip economy has grown since market creation.
- `place_trade` always writes `cost_millis` and `shares_millis`; no new fixed-chip trade path exists.
- `settle_market` pays winning shares, awards Beer Karma, writes `MARKET_PAYOUT` ledger events, and refuses already resolved markets.
- `project_trip_markets` returns current odds, odds history, positions, mark value, P/L, possible payouts, resolved payouts, and World Cup metadata matching today's API payload.
- `market_performance` ranks settled-market performance and ignores open markets.
- Projection and performance tolerate old rows missing `cost_millis` or `shares_millis` only by applying the existing read fallback.

Old tests to delete or rewrite after migration:

- Direct tests of `Market.shares_for_cost` and `Market.share_market_state` should move to boundary assertions through `place_trade` and `project_trip_markets`.
- Direct tests of `Market.resolve` should move to `settle_market`, while admin and World Cup tests assert their callers use the boundary.
- Endpoint tests that duplicate service invariants should become thinner HTTP contract tests after `place_trade` is covered directly.

Test environment needs:

- Django `TestCase` with the normal local test database.
- Local `WorldCupFixture` and `WorldCupMarket` rows for tradeability cases.
- No football-data.org client, network access, or provider mocks.

## Implementation Recommendations

The Beermarket module should own the market accounting invariants. It should hide pricing internals, transaction ordering, ledger writes, settlement payout math, World Cup tradeability lookup, and read-model construction.

Callers should expose transport concerns only:

- Views parse JSON and return `JsonResponse`.
- Admin actions decide which selected markets are eligible for manual settlement.
- World Cup sync decides the fixture-derived outcome, then calls the settlement boundary.
- `trip_results` asks for market projections instead of rebuilding market internals.

Migration sequence:

1. Add `scheduler/beermarket.py` with `place_trade`, `TradeReceipt`, and `BeermarketError`.
2. Move chip parsing and trade transaction logic from `market_trade_api` into `place_trade`.
3. Add boundary tests for `place_trade`, then keep the existing endpoint tests as regression coverage.
4. Move `Market.resolve` behavior into `settle_market`; keep `Market.resolve` temporarily as a compatibility wrapper if needed.
5. Move market projection code from `trip_results` into `project_trip_markets`.
6. Move settled performance code into `market_performance`.
7. After callers are migrated, make `Market` and `MarketTrade` persistence-focused models; avoid public pricing or settlement methods on them unless they are thin compatibility wrappers.

Non-goals:

- Do not reintroduce the old fixed-chip market implementation.
- Do not add a generic market-type registry until there is a concrete second current market model.
- Do not change user-visible trading, pricing, payout, or response behavior as part of this refactor.
