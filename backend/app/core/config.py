from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent.parent   # crypto-quant-platform/backend/
DATA_DIR    = BACKEND_DIR / "data"

PAPER_FILE          = DATA_DIR / "paper_account.json"
SIGNALS_LOG         = DATA_DIR / "signals_log.json"
SIGNALS_JSONL       = DATA_DIR / "signals_history.jsonl"
STATE_FILE          = DATA_DIR / "state.json"
EQUITY_JSONL        = DATA_DIR / "equity_history.jsonl"
TRADE_RECORDS_DIR   = DATA_DIR / "trade_records"
CLOSED_TRADES_JSONL = TRADE_RECORDS_DIR / "closed_trades.jsonl"
KLINES_CACHE_DIR    = DATA_DIR / "klines"
