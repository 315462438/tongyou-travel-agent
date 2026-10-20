import asyncio
import json
import pytest
from app.tools import place_details as details
from test_trip_collab import client
from app.db.models import TravelMessage, TravelTrip


def test_matching_requires_name_and_nearby_coordinate():
    poi={"name":"西湖","location":"120.15,30.25"}
    assert details.matching_poi("西湖", "120.15,30.25", [poi]) == poi
    assert details.matching_poi("西湖", "116.4,39.9", [poi]) is None
    assert details.matching_poi("机场", "120.15,30.25", [poi]) is None
    assert details.matching_poi("西湖", "nan,30", [poi]) is None
    assert details.matching_poi("西湖", "", [poi]) is None


def test_guide_only_matching_images_and_bounded_excerpt():
    meta={"sources":[{"images":[{"name":"西湖","url":"https://a.amap.com/a.jpg"},{"name":"其他地点","url":"https://a.amap.com/b.jpg"},{"name":"西湖","url":"http://127.0.0.1/private"}]}]}
    excerpt, photos=details.guide_material("西湖","别处内容\n\n西湖：沿湖散步。\n\n私人其他段落",json.dumps(meta))
    assert excerpt == "西湖：沿湖散步。"
    assert len(photos)==1 and photos[0]["url"].startswith('/api/img?u=')
    assert details.guide_material("西湖", "", "[]")==("",[])


def test_public_cache_and_no_cross_request_mutation(monkeypatch):
    details._cache.clear();monkeypatch.setattr(details.amap,'enabled',lambda:True)
    calls=[]
    async def fake(*args,**kwargs):
        calls.append(kwargs)
        return {"pois":[{"name":"西湖","location":"120.15,30.25","address":"西湖风景区","type":"风景名胜","photos":[{"url":"https://a.amap.com/a.jpg"},{"url":"https://evil.invalid/a.jpg"}]}]}
    monkeypatch.setattr(details.amap,'_call',fake)
    async def run():
        a=await details.public_details('西湖','120.15,30.25');a['photos'].clear()
        b=await details.public_details('西湖','120.15,30.25')
        assert len(b['photos'])==1 and len(calls)==1
        assert b['facts'][0]['value']=='西湖风景区'
        assert 'description' not in b
        assert (await details.public_details('独立广场','101.69,3.14'))['status']=='unavailable'
        assert len(calls)==1
    asyncio.run(run())


def test_provider_error_does_not_break_existing_description(monkeypatch):
    details._cache.clear();monkeypatch.setattr(details.amap,'enabled',lambda:True)
    async def fail(*a,**kw):raise TimeoutError()
    monkeypatch.setattr(details.amap,'_call',fail)
    value=asyncio.run(details.public_details('西湖','120.15,30.25'))
    assert value=={'status':'temporary_error','photos':[],'facts':[]}


def test_member_and_stop_ownership_before_provider(client,monkeypatch):
    c,current=client;calls=[]
    async def fake(name,loc):calls.append(name);return {'status':'unavailable','photos':[],'facts':[]}
    monkeypatch.setattr(details,'public_details',fake)
    tid=c.post('/api/trips',json={'title':'杭州','days':2}).json()['id']
    sid=c.post(f'/api/trips/{tid}/stops',json={'day':1,'name':'西湖','note':'自己的安排'}).json()['id']
    other=c.post('/api/trips',json={'title':'另一行程','days':1}).json()['id']
    assert c.get(f'/api/trips/{other}/stops/{sid}/details').status_code==404
    current['id']='ub'
    assert c.get(f'/api/trips/{tid}/stops/{sid}/details').status_code==404
    current['id']='ua';c.post(f'/api/trips/{tid}/invite',json={'username':'bob'})
    current['id']='ub'
    assert c.get(f'/api/trips/{tid}/stops/{sid}/details').status_code==404
    assert calls==[]
    c.post(f'/api/trips/{tid}/invites/respond',json={'accept':True})
    response=c.get(f'/api/trips/{tid}/stops/{sid}/details')
    assert response.status_code==200 and response.json()['description']=='自己的安排'
    assert calls==['西湖']


def test_only_imported_assistant_material_is_exposed(client,monkeypatch):
    c,current=client
    async def fake(*a):return {'status':'unavailable','photos':[],'facts':[]}
    monkeypatch.setattr(details,'public_details',fake)
    tid=c.post('/api/trips',json={'title':'杭州','days':1}).json()['id']
    sid=c.post(f'/api/trips/{tid}/stops',json={'day':1,'name':'西湖'}).json()['id']
    with c.app.state.test_maker() as db:
        trip=db.get(TravelTrip,tid);trip.source_message_id='m1';trip.source_conversation_id='c1'
        db.add(TravelMessage(id='m1',conversation_id='c1',role='assistant',content='西湖：漫步湖边。\n\n其他私密内容',meta_json='{}'));db.commit()
    data=c.get(f'/api/trips/{tid}/stops/{sid}/details').json()
    assert data['guide_excerpt']=='西湖：漫步湖边。'
    assert 'conversation_id' not in data
    with c.app.state.test_maker() as db:
        db.get(TravelMessage,'m1').role='user';db.commit()
    assert c.get(f'/api/trips/{tid}/stops/{sid}/details').json()['guide_excerpt']==''


def test_provider_retry_is_not_stuck_in_error_cache(monkeypatch):
    details._cache.clear();monkeypatch.setattr(details.amap,'enabled',lambda:True)
    calls=[]
    async def provider(*a,**kw):
        calls.append(1)
        return None if len(calls)==1 else {'pois':[{'name':'西湖','location':'120.15,30.25'}]}
    monkeypatch.setattr(details.amap,'_call',provider)
    async def run():
        assert (await details.public_details('西湖','120.15,30.25'))['status']=='temporary_error'
        assert (await details.public_details('西湖','120.15,30.25'))['status']=='ready'
    asyncio.run(run());assert len(calls)==2
