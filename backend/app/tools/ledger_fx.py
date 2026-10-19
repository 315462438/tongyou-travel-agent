"""在线最新参考汇率；不把硬编码兜底价格计入账本总额。"""
import time
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import httpx

_CACHE: dict[tuple, dict] = {}


async def convert_totals(totals: dict[str, int], target: str, refresh: bool = False) -> dict:
    quotes = sorted(c for c in totals if c != target)
    key = (target, tuple(quotes))
    cached = _CACHE.get(key)
    now = time.time()
    data = cached
    stale = False
    if quotes and (not cached or now - cached['ts'] >= (30 if refresh else 900)):
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=8) as client:
                response = await client.get('https://api.frankfurter.dev/v2/rates', params={'base': target, 'quotes': ','.join(quotes)})
                response.raise_for_status()
                rows = response.json()
            if not isinstance(rows, list):
                raise ValueError("Malformed rate response")
            rates = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if row.get('base') != target or row.get('quote') not in quotes:
                    continue
                rate = Decimal(str(row['rate']))
                day = date.fromisoformat(row['date'])
                age = (datetime.now(timezone.utc).date() - day).days
                if rate.is_finite() and rate > 0 and 0 <= age <= 7:
                    rates[row['quote']] = {'rate': str(Decimal(1) / rate), 'date': day.isoformat()}
            data = {'ts': now, 'rates': rates, 'fetched_at': datetime.now(timezone.utc).isoformat()}
            # 不缓存空失败，避免一次异常让用户长期拿不到汇率。
            if rates:
                if len(_CACHE) >= 128:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[key] = data
        except (httpx.HTTPError, ValueError, TypeError, KeyError, ArithmeticError):
            stale = True
            data = cached
    items = []
    missing = []
    for currency, minor in sorted(totals.items()):
        quote = {'rate': '1', 'date': ''} if currency == target else (data or {}).get('rates', {}).get(currency)
        if quote and quote['date'] and (datetime.now(timezone.utc).date() - date.fromisoformat(quote['date'])).days > 7:
            quote = None
        if not quote:
            missing.append(currency)
            continue
        converted = int((Decimal(minor) * Decimal(quote['rate'])).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        items.append({'currency': currency, 'original_minor': minor, 'converted_minor': converted, 'rate': quote['rate'], 'rate_date': quote['date']})
    return {'target_currency': target, 'total_minor': None if missing else sum(i['converted_minor'] for i in items),
            'items': items, 'missing': missing, 'stale': stale,
            'source': 'Frankfurter' if quotes else 'same_currency',
            'fetched_at': (data or {}).get('fetched_at', '')}
