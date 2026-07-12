# Binance connector (first production-grade connector)

The Binance connector (`app/connectors/binance.py`) is the first connector in
this service that talks to a **real** broker API: Binance spot REST v3 plus
combined-stream websockets. The other 7 connectors still use the placeholder
REST paths in `app/connectors/http_base.py`.

## Creating testnet keys

1. Go to https://testnet.binance.vision and log in with a GitHub account.
2. "Generate HMAC-SHA256 Key" -> copy the API key and secret (the secret is
   shown only once).
3. Testnet balances are fake and reset periodically; endpoints mirror
   production `api/v3` shapes.
4. Connect through this service with `demo: true` (the default):

```
POST /connectors/binance/connect
{"api_key": "...", "api_secret": "...", "demo": true}
```

`demo: true` targets the testnet, `demo: false` targets production. Never
point real keys at the testnet or vice versa - the key spaces are separate.

## Configuration knobs

Environment variables (checked at request time):

| Variable | Default | Used when |
|---|---|---|
| `BINANCE_TESTNET_URL` | `https://testnet.binance.vision` | `demo: true` |
| `BINANCE_API_URL` | `https://api.binance.com` | `demo: false` |
| `BINANCE_TESTNET_WS_URL` | `wss://stream.testnet.binance.vision` | `demo: true` |
| `BINANCE_WS_URL` | `wss://stream.binance.com:9443` | `demo: false` |

Per-connector config (`BrokerConfig.extra`):

| Key | Default | Meaning |
|---|---|---|
| `base_url` / `ws_url` | - | Hard override, wins over env vars |
| `quote_asset` | `USDT` | Asset used for `AccountState` and excluded from holdings |
| `recv_window_ms` | `5000` | Binance `recvWindow` for SIGNED requests |
| `kline_page_limit` | `1000` | Klines fetched per page when paginating history |

Deployment env vars belong in `infra/docker/*` (owned by another workstream;
not modified here) - the service only reads the variables above.

## What is real

* `GET /api/v3/klines` (historical Bars, timeframe -> interval mapping, pagination)
* `GET /api/v3/ticker/bookTicker` (Tick)
* `POST /api/v3/order` / `DELETE /api/v3/order` (place/cancel, HMAC-SHA256 signed)
* `GET /api/v3/account` (AccountState + holdings)
* `GET /api/v3/openOrders`, `GET /api/v3/myTrades` (cancel fallback, report helpers)
* `GET /api/v3/exchangeInfo` symbol filters, cached: quantities are floored to
  `LOT_SIZE.stepSize`, prices to `PRICE_FILTER.tickSize`, and orders below
  `MIN_NOTIONAL`/`NOTIONAL` are rejected locally with a clear error before any
  network call.
* Websocket market data: `<symbol>@bookTicker` and `<symbol>@kline_<interval>`
  over a combined stream, with backoff reconnect + resubscribe
  (`app/connectors/binance_ws.py`).
* Rate limiting by request **weight** (1200 weight/min budget) through the
  shared token bucket; HTTP 429/418 drains the bucket, honours `Retry-After`
  once and then surfaces `BinanceRateLimitError`.
* Binance error codes map to typed exceptions (`-1013` filters, `-2010`
  insufficient balance, `-1021` clock skew, `-2011/-2013` unknown order), which
  the FastAPI layer converts to 422/429/404 responses.

## Spot vs futures: what "positions" means

This connector uses the **spot** API. Spot accounts have no positions, margin
or leverage - you simply own asset balances. Therefore:

* `get_positions()` returns *holdings* derived from `GET /api/v3/account`
  balances: every non-quote asset with a non-zero (free+locked) balance.
* `average_price` is reported as `0.0` because spot balances carry no cost
  basis; reconstruct one from `get_my_trades(symbol)` if a strategy needs it.
* `AccountState` is a quote-asset (default USDT) view: `margin_used` = quote
  locked by open orders, `free_margin` = free quote. `equity == balance`
  because valuing non-quote holdings would require per-asset tickers (TODO).

Real positions/leverage require the **USD-M futures** API (`/fapi/...`,
`fstream.binance.com`) - a separate endpoint family and a natural follow-up
connector variant.

## Promoting this pattern to the other 7 connectors

Per connector, repeat what was done here:

1. Keep subclassing `BaseHTTPConnector` for transport/rate-limit/reconnect;
   override the CRUD methods with the broker's real paths and payloads.
2. Put auth in a sibling `<broker>_auth.py` and unit-test it against the
   signature fixture published in that broker's docs.
3. Raise the shared taxonomy in `app/connectors/errors.py` from broker error
   codes so `app/main.py` needs no new handlers.
4. Pass per-endpoint weights/costs to `TokenBucketRateLimiter.acquire(weight)`
   and call `drain()` on the broker's throttle signal.
5. Stream via a `<broker>_ws.py` client with an injectable connect factory;
   test with scripted in-process fakes (see `tests/binance_mocks.py`).
6. Update `app/broker_limits.py` with the broker's documented budget.

## TODOs / future work

* User-data stream (`/api/v3/userDataStream` + listenKey keepalive) for
  push-based fill/execution reports instead of order-response snapshots.
* Futures (USD-M) support for real positions and leverage.
* Equity valuation of non-quote holdings via ticker prices.
* OCO orders and `STOP_LOSS_LIMIT` with distinct stop/limit prices (the shared
  `Order` model carries a single price today, used as both).
