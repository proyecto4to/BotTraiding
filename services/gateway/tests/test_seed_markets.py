"""seed_markets fills the markets table outside Alembic.

The Alembic migration seeds these against Postgres, but the local Windows
start-up creates tables with `create_all` (the migrations use Postgres-specific
types), so the table stayed empty and the dashboard's Markets page reported "no
markets configured". This runs on every boot, so being idempotent — and leaving
an admin's choices alone — is the whole contract.
"""

from __future__ import annotations

# Via the module, not `from app.db import SessionLocal`: the conftest swaps in a
# session bound to the in-memory test engine, and a direct import would capture
# the original before that happens.
from app import db as db_module
from app.models import Market
from app.seed_data import MARKET_SEED, seed_markets


def test_seeds_every_market_on_an_empty_table():
    with db_module.SessionLocal() as db:
        db.query(Market).delete()
        db.commit()

        added = seed_markets(db)

        assert added == len(MARKET_SEED)
        assert db.query(Market).count() == len(MARKET_SEED)
        assert {m.code for m in db.query(Market).all()} == {m["code"] for m in MARKET_SEED}


def test_running_again_adds_nothing():
    with db_module.SessionLocal() as db:
        db.query(Market).delete()
        db.commit()
        seed_markets(db)

        assert seed_markets(db) == 0
        assert db.query(Market).count() == len(MARKET_SEED)


def test_does_not_re_enable_a_market_an_admin_turned_off():
    """Booting the stack must not silently undo an operator's decision."""
    with db_module.SessionLocal() as db:
        db.query(Market).delete()
        db.commit()
        seed_markets(db)

        crypto = db.query(Market).filter(Market.code == "CRYPTO").one()
        crypto.enabled = False
        db.commit()

        seed_markets(db)

        assert db.query(Market).filter(Market.code == "CRYPTO").one().enabled is False


def test_fills_in_only_what_is_missing():
    with db_module.SessionLocal() as db:
        db.query(Market).delete()
        db.commit()
        seed_markets(db)
        db.query(Market).filter(Market.code == "BONDS").delete()
        db.commit()

        assert seed_markets(db) == 1
        assert db.query(Market).count() == len(MARKET_SEED)
