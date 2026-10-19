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
