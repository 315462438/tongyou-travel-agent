import time

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/fx", tags=["fx"])

SUPPORTED_CURRENCIES = {
    "CNY": {"name": "人民币", "symbol": "¥", "rate_to_cny": 1.0},
    "MYR": {"name": "马币", "symbol": "RM", "rate_to_cny": 1.55},
    "USD": {"name": "美元", "symbol": "$", "rate_to_cny": 7.2},
    "EUR": {"name": "欧元", "symbol": "€", "rate_to_cny": 7.85},
    "GBP": {"name": "英镑", "symbol": "£", "rate_to_cny": 9.15},
    "JPY": {"name": "日元", "symbol": "¥", "rate_to_cny": 0.049},
    "KRW": {"name": "韩元", "symbol": "₩", "rate_to_cny": 0.0052},
    "THB": {"name": "泰铢", "symbol": "฿", "rate_to_cny": 0.205},
    "SGD": {"name": "新币", "symbol": "S$", "rate_to_cny": 5.35},
    "HKD": {"name": "港币", "symbol": "HK$", "rate_to_cny": 0.92},
    "TWD": {"name": "台币", "symbol": "NT$", "rate_to_cny": 0.225},
    "AUD": {"name": "澳元", "symbol": "A$", "rate_to_cny": 4.7},
    "CAD": {"name": "加元", "symbol": "C$", "rate_to_cny": 5.25},
    "IDR": {"name": "印尼盾", "symbol": "Rp", "rate_to_cny": 0.00044},
    "VND": {"name": "越南盾", "symbol": "₫", "rate_to_cny": 0.00028},
}

_CACHE: dict[str, object] = {"ts": 0.0, "data": None}
_CACHE_TTL_SECONDS = 6 * 60 * 60


def _fallback_payload() -> dict:
    return {
        "base": "CNY",
        "source": "fallback",
        "updated_at": "",
        "currencies": [
            {"code": code, **meta}
            for code, meta in SUPPORTED_CURRENCIES.items()
        ],
    }


async def _fetch_frankfurter() -> dict | None:
    codes = [code for code in SUPPORTED_CURRENCIES if code != "CNY"]
    url = "https://api.frankfurter.app/latest"
    async with httpx.AsyncClient(trust_env=False, timeout=8) as client:
        response = await client.get(url, params={"from": "CNY", "to": ",".join(codes)})
        response.raise_for_status()
        data = response.json()
    rates = data.get("rates") or {}
    currencies = [{"code": "CNY", **SUPPORTED_CURRENCIES["CNY"]}]
    for code in codes:
        meta = SUPPORTED_CURRENCIES[code]
        quote = float(rates.get(code) or 0)
        rate_to_cny = round(1 / quote, 6) if quote > 0 else meta["rate_to_cny"]
        currencies.append({"code": code, **meta, "rate_to_cny": rate_to_cny})
    return {
        "base": "CNY",
        "source": "frankfurter",
        "updated_at": data.get("date") or "",
        "currencies": currencies,
    }


@router.get("/rates")
async def fx_rates() -> dict:
    now = time.time()
    cached = _CACHE.get("data")
    if cached and now - float(_CACHE.get("ts") or 0) < _CACHE_TTL_SECONDS:
        return cached  # type: ignore[return-value]

    try:
        data = await _fetch_frankfurter()
    except Exception:
        data = None
    payload = data or _fallback_payload()
    _CACHE.update({"ts": now, "data": payload})
    return payload
