"""Versioned Food-owned registry copied as a contract, no domain imports."""
import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1]/'schemas/nutrients.v1.json').read_text(encoding='utf-8'))['nutrients']
