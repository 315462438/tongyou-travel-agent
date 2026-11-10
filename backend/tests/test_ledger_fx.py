import asyncio
from datetime import datetime,timezone,timedelta
import httpx
import pytest
from app.tools import ledger_fx as fx

@pytest.fixture(autouse=True)
def reset():
    fx._CACHE.clear();yield;fx._CACHE.clear()

def fake(monkeypatch,rows=None,fail=False):
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,url,params):
            calls.append(params)
            if fail:raise httpx.ConnectError('offline')
            return httpx.Response(200,json=rows,request=httpx.Request('GET',url))
    monkeypatch.setattr(fx.httpx,'AsyncClient',Client)
    return calls

def row(code,rate='0.625'):
    return {'base':'CNY','quote':code,'rate':rate,'date':datetime.now(timezone.utc).date().isoformat()}

def test_myr_to_cny_precision_and_cache_refresh(monkeypatch):
    calls=fake(monkeypatch,[row('MYR')]);first=asyncio.run(fx.convert_totals({'MYR':10001,'CNY':100},'CNY'))
    assert first['total_minor']==16102 and first['items'][1]['rate']=='1.6'
    assert first['source']=='Frankfurter' and first['fetched_at'] and not first['stale']
    asyncio.run(fx.convert_totals({'MYR':10001,'CNY':100},'CNY',True));assert len(calls)==1
    for cached in fx._CACHE.values():cached['ts']-=31
    asyncio.run(fx.convert_totals({'MYR':10001,'CNY':100},'CNY',True));assert len(calls)==2

def test_partial_quotes_no_partial_total(monkeypatch):
    fake(monkeypatch,[row('MYR')]);r=asyncio.run(fx.convert_totals({'MYR':10000,'USD':500},'CNY'))
    assert r['total_minor'] is None and r['missing']==['USD']

@pytest.mark.parametrize('rate',['0','-1','NaN','Infinity'])
def test_bad_quotes(monkeypatch,rate):
    fake(monkeypatch,[row('MYR',rate)]);assert asyncio.run(fx.convert_totals({'MYR':100},'CNY'))['total_minor'] is None

def test_failure_and_stale_cache(monkeypatch):
    fake(monkeypatch,fail=True);assert asyncio.run(fx.convert_totals({'MYR':100},'CNY'))['total_minor'] is None
    fake(monkeypatch,[row('MYR')]);asyncio.run(fx.convert_totals({'MYR':100},'CNY'))
    for cached in fx._CACHE.values():cached['ts']-=901
    fake(monkeypatch,fail=True);r=asyncio.run(fx.convert_totals({'MYR':100},'CNY'))
    assert r['total_minor']==160 and r['stale'] is True
    for cached in fx._CACHE.values():cached['rates']['MYR']['date']=(datetime.now(timezone.utc).date()-timedelta(days=8)).isoformat()
    assert asyncio.run(fx.convert_totals({'MYR':100},'CNY'))['total_minor'] is None

def test_same_currency_and_empty_no_network(monkeypatch):
    calls=fake(monkeypatch,fail=True)
    assert asyncio.run(fx.convert_totals({'CNY':1234},'CNY'))['total_minor']==1234
    assert asyncio.run(fx.convert_totals({},'CNY'))['total_minor']==0
    assert not calls


def dated_row(base, quote, rate, days=0):
    """days > 0 represents Frankfurter's pre-published next-day observation."""
    day = datetime.now(timezone.utc).date() + timedelta(days=days)
    return {'base': base, 'quote': quote, 'rate': rate, 'date': day.isoformat()}


@pytest.mark.parametrize('days,expected', [(-8, None), (-7, 2016), (0, 2016), (1, 2016), (2, None)])
def test_cny_to_sgd_observation_date_window(monkeypatch, days, expected):
    # Production reproduction: SGD/CNY = 5.219, with a next-day rate date.
    quote = dated_row('SGD', 'CNY', '5.219', days)
    fake(monkeypatch, [quote])
    result = asyncio.run(fx.convert_totals({'CNY': 10000, 'SGD': 100}, 'SGD'))
    assert result['total_minor'] == expected
    assert result['missing'] == ([] if expected is not None else ['CNY'])
    if expected is not None:
        assert result['items'][0]['rate_date'] == quote['date']
        assert result['items'][0]['original_minor'] == 10000
        assert result['items'][0]['converted_minor'] == 1916


def test_reverse_sgd_conversion_with_next_day_rate(monkeypatch):
    fake(monkeypatch, [dated_row('CNY', 'SGD', '0.2', 1)])
    result = asyncio.run(fx.convert_totals({'SGD': 10000}, 'CNY'))
    assert result['total_minor'] == 50000 and result['missing'] == []


@pytest.mark.parametrize('bad', [
    {'base': 'SGD', 'quote': 'USD', 'rate': 'bad', 'date': '2026-10-24'},
    {'base': 'SGD', 'quote': 'USD', 'rate': '0.75', 'date': 'not-a-date'},
    {'base': 'SGD', 'quote': 'USD', 'rate': '0.75', 'date': None},
    {'base': 'SGD', 'quote': 'USD', 'date': '2026-10-24'},
])
def test_invalid_row_does_not_discard_other_currency(monkeypatch, bad):
    fake(monkeypatch, [bad, dated_row('SGD', 'CNY', '5.219', 1)])
    result = asyncio.run(fx.convert_totals({'CNY': 10000, 'USD': 500}, 'SGD'))
    assert result['total_minor'] is None and result['missing'] == ['USD']
    assert result['items'][0]['currency'] == 'CNY'
    assert result['items'][0]['converted_minor'] == 1916


def test_next_day_cache_survives_outage_without_changing_date(monkeypatch):
    quote = dated_row('SGD', 'CNY', '5.219', 1)
    fake(monkeypatch, [quote])
    first = asyncio.run(fx.convert_totals({'CNY': 10000}, 'SGD'))
    for cached in fx._CACHE.values():
        cached['ts'] -= 901
    fake(monkeypatch, fail=True)
    result = asyncio.run(fx.convert_totals({'CNY': 10000}, 'SGD'))
    assert result['total_minor'] == 1916 and result['stale'] is True
    assert result['items'][0]['rate_date'] == quote['date']
    assert result['fetched_at'] == first['fetched_at']


@pytest.mark.parametrize('days', [-8, 2])
def test_cached_dates_obey_same_window_as_fresh_dates(monkeypatch, days):
    fake(monkeypatch, [dated_row('SGD', 'CNY', '5.219')])
    asyncio.run(fx.convert_totals({'CNY': 10000}, 'SGD'))
    for cached in fx._CACHE.values():
        cached['rates']['CNY']['date'] = dated_row('SGD', 'CNY', '5.219', days)['date']
    result = asyncio.run(fx.convert_totals({'CNY': 10000}, 'SGD'))
    assert result['total_minor'] is None and result['missing'] == ['CNY']


def test_invalid_response_not_cached_and_next_call_recovers(monkeypatch):
    fake(monkeypatch, [dated_row('SGD', 'CNY', '5.219', 2)])
    assert asyncio.run(fx.convert_totals({'CNY': 10000}, 'SGD'))['total_minor'] is None
    assert not fx._CACHE
    calls = fake(monkeypatch, [dated_row('SGD', 'CNY', '5.219', 1)])
    assert asyncio.run(fx.convert_totals({'CNY': 10000}, 'SGD'))['total_minor'] == 1916
    assert len(calls) == 1
