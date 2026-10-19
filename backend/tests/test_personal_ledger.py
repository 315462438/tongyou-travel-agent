"""个人账本真实 HTTP/数据库回归，不接触生产数据。"""
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import models as m
from app.api import ledger_api, trip_api
from app.api.deps import get_current_user
from app.db.session import get_db

@pytest.fixture
def ctx():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def fk(conn,_): conn.execute('PRAGMA foreign_keys=ON')
    m.Base.metadata.create_all(engine);maker=sessionmaker(bind=engine)
    with maker() as db:
        db.add_all([m.TravelUser(id='a',username='alice',password_hash='x'),m.TravelUser(id='b',username='bob',password_hash='x')]);db.commit()
    current=['a']; app=FastAPI();app.include_router(ledger_api.router);app.include_router(trip_api.router)
    def user():
        with maker() as db:return db.get(m.TravelUser,current[0])
    def database():
        with maker() as db:yield db
    app.dependency_overrides[get_current_user]=user;app.dependency_overrides[get_db]=database
    with TestClient(app) as client:yield client,current,maker
    engine.dispose()

def book(c):
    r=c.post('/api/ledger',json={'title':'马来西亚旅行'});assert r.status_code==200
    return r.json()['id']

def body():
    return dict(id=str(uuid.uuid4()),title='晚餐',amount='12.34',currency='MYR',category='餐饮',spent_at='2026-10-19',note='海边')

def test_crud_precision_idempotency_currency(ctx):
    c,_,_=ctx;b=book(c);path=f'/api/ledger/{b}';data=body()
    first=c.post(path+'/entries',json=data);assert first.status_code==200;eid=first.json()['id']
    assert c.post(path+'/entries',json=data).json()==first.json()
    data['amount']='12.35';assert c.post(path+'/entries',json=data).status_code==409
    assert c.patch(path+'/entries/'+eid,json=data).status_code==200
    assert c.patch(path+'/currency',json={'target_currency':'USD'}).status_code==200
    assert c.patch(path,json={'title':'假期账本'}).status_code==200
    d=c.get(path).json();assert d['title']=='假期账本' and d['totals']=={'MYR':1235} and d['target_currency']=='USD'
    assert d['by_category']==[{'currency':'MYR','category':'餐饮','amount_minor':1235}]
    assert d['by_day'][0]['amount_minor']==1235
    assert c.delete(path+'/entries/'+eid).status_code==200
    assert c.get(path).json()['totals']=={}

@pytest.mark.parametrize('field,value',[('amount','0'),('amount','-2'),('amount','1.001'),('amount','NaN'),('amount','Infinity'),('amount','10000000'),('title','x'*81),('spent_at','2026-02-30'),('currency','XXX'),('category','xx'),('note','x'*501)])
def test_invalid_entry(ctx,field,value):
    c,_,_=ctx;b=book(c);data=body();data[field]=value
    assert c.post(f'/api/ledger/{b}/entries',json=data).status_code==422
    assert c.get(f'/api/ledger/{b}').json()['count']==0

def test_user_isolation_and_cross_book(ctx):
    c,current,_=ctx;b=book(c);b2=book(c);data=body()
    eid=c.post(f'/api/ledger/{b}/entries',json=data).json()['id']
    assert c.patch(f'/api/ledger/{b2}/entries/{eid}',json=data).status_code==404
    assert c.delete(f'/api/ledger/{b2}/entries/{eid}').status_code==404
    current[0]='b';assert c.get('/api/ledger').json()==[]
    for method,path,payload in [('GET',f'/{b}',None),('GET',f'/{b}/conversion',None),('DELETE',f'/{b}',None),('POST',f'/{b}/entries',data),('PATCH',f'/{b}/currency',{'target_currency':'USD'}),('PATCH',f'/{b}',{'title':'偷改'}),('DELETE',f'/{b}/entries/{eid}',None)]:
        assert c.request(method,'/api/ledger'+path,json=payload).status_code==404
    current[0]='a';assert c.get(f'/api/ledger/{b}').json()['count']==1

def test_book_delete_removes_only_own_entries(ctx):
    c,_,maker=ctx;b=book(c);b2=book(c)
    for bid in (b,b2):assert c.post(f'/api/ledger/{bid}/entries',json=body()).status_code==200
    assert c.delete(f'/api/ledger/{b}').status_code==200
    with maker() as db:assert len(db.scalars(select(m.TravelLedgerEntry)).all())==1
    assert c.get(f'/api/ledger/{b2}').json()['count']==1

def test_conversion_saved_preference_and_unchanged_originals(ctx,monkeypatch):
    c,_,_=ctx;b=book(c);c.post(f'/api/ledger/{b}/entries',json=body());c.patch(f'/api/ledger/{b}/currency',json={'target_currency':'USD'})
    async def fake(totals,target,refresh):
        assert totals=={'MYR':1234} and target=='USD' and refresh is True
        return {'total_minor':300,'target_currency':target}
    monkeypatch.setattr('app.tools.ledger_fx.convert_totals',fake)
    assert c.get(f'/api/ledger/{b}/conversion?refresh=true').json()['total_minor']==300
    assert c.get(f'/api/ledger/{b}').json()['totals']=={'MYR':1234}

def test_ledger_requires_auth(ctx):
    c,_,_=ctx;c.app.dependency_overrides.pop(get_current_user)
    assert c.get('/api/ledger').status_code==401

def test_leave_and_delete_complete_children(ctx):
    c,current,maker=ctx;tid=c.post('/api/trips',json={'title':'共同旅行','days':2}).json()['id']
    with maker() as db:
        db.add(m.TravelTripMember(trip_id=tid,user_id='b',role='editor',status='accepted'))
        db.add(m.TravelTripExpense(trip_id=tid,payer_user_id='b',amount=20,title='午餐',participants_json='["a","b"]',created_by='b'))
        db.add(m.TravelNotification(user_id='b',actor_id='a',type='trip_chat',title='群聊',target_kind='trip',target_id=tid,dedupe_key='test-trip'));db.commit()
    assert c.post(f'/api/trips/{tid}/leave').status_code==403
    current[0]='b';assert c.delete(f'/api/trips/{tid}').status_code==403
    assert c.post(f'/api/trips/{tid}/leave').status_code==200
    assert c.get('/api/trips').json()==[] and c.get(f'/api/trips/{tid}').status_code==404
    with maker() as db:
        assert db.get(m.TravelTrip,tid)
        assert len(db.scalars(select(m.TravelTripExpense)).all())==1
        assert not db.scalars(select(m.TravelNotification)).all()
    current[0]='a'
    children=[m.TravelTripStop,m.TravelTripComment,m.TravelTripChatMessage,m.TravelTripSuggestion,m.TravelTripFood,m.TravelTripPackingItem,m.TravelTripPackingState,m.TravelTripTip]
    with maker() as db:
        for model in children:
            values={'trip_id':tid}
            for col in model.__table__.columns:
                if col.name!='trip_id' and not col.nullable and col.default is None:values[col.name]=0 if col.type.python_type is int else 'x'
            db.add(model(**values))
        db.commit()
    assert c.delete(f'/api/trips/{tid}').status_code==200
    with maker() as db:
        assert db.get(m.TravelTrip,tid) is None
        for model in children+[m.TravelTripExpense,m.TravelTripEvent,m.TravelTripMember]:assert not db.scalars(select(model).where(model.trip_id==tid)).all()

def test_optional_trip_link_and_legacy_rename(ctx):
    c,current,maker=ctx
    tid=c.post('/api/trips',json={'title':'马来西亚','days':3}).json()['id']
    linked=c.post('/api/ledger',json={'title':'旅行花费','trip_id':tid}).json()
    bid=linked['id'];path=f'/api/ledger/{bid}'
    assert linked['trip']=={'id':tid,'title':'马来西亚'}
    independent=book(c)
    assert len(c.get('/api/ledger',params={'trip_id':tid}).json())==1
    assert c.patch(path,json={'title':'旧客户端改名'}).status_code==200
    assert c.get(path).json()['trip']['id']==tid
    current[0]='b'
    assert c.post('/api/ledger',json={'title':'越权关联','trip_id':tid}).status_code==404
    assert c.get('/api/ledger',params={'trip_id':tid}).status_code==404
    assert c.patch(path,json={'title':'越权','trip_id':None}).status_code==404
    with maker() as db:
        db.add(m.TravelTripMember(trip_id=tid,user_id='b',role='editor',status='pending'));db.commit()
    assert c.post('/api/ledger',json={'title':'待接受','trip_id':tid}).status_code==404
    current[0]='a'
    assert c.patch(path,json={'title':'解除关联','trip_id':None}).status_code==200
    assert c.get(path).json()['trip'] is None
    assert c.get('/api/ledger',params={'trip_id':tid}).json()==[]
    assert c.get(f'/api/ledger/{independent}').json()['trip'] is None


def test_linked_personal_books_survive_exit_and_trip_deletion(ctx):
    c,current,maker=ctx
    tid=c.post('/api/trips',json={'title':'同行','days':2}).json()['id']
    with maker() as db:
        db.add(m.TravelTripMember(trip_id=tid,user_id='b',role='editor',status='accepted'));db.commit()
    bids={}
    for uid in ('a','b'):
        current[0]=uid
        bids[uid]=c.post('/api/ledger',json={'title':'私人花费','trip_id':tid}).json()['id']
        assert c.post(f'/api/ledger/{bids[uid]}/entries',json=body()).status_code==200
        assert len(c.get('/api/ledger',params={'trip_id':tid}).json())==1
    assert c.get(f'/api/ledger/{bids["a"]}').status_code==404
    assert c.post(f'/api/trips/{tid}/leave').status_code==200
    assert c.get(f'/api/ledger/{bids["b"]}').json()['trip'] is None
    current[0]='a'
    assert c.get(f'/api/ledger/{bids["a"]}').json()['trip']['id']==tid
    assert c.delete(f'/api/trips/{tid}').status_code==200
    for uid,bid in bids.items():
        current[0]=uid;result=c.get(f'/api/ledger/{bid}').json()
        assert result['trip'] is None and result['count']==1 and result['totals']=={'MYR':1234}


def test_hidden_trip_after_membership_revoked(ctx):
    c,_,maker=ctx
    tid=c.post('/api/trips',json={'title':'已移除权限','days':1}).json()['id']
    bid=c.post('/api/ledger',json={'title':'个人','trip_id':tid}).json()['id']
    with maker() as db:
        db.delete(db.get(m.TravelTripMember,(tid,'a')));db.commit()
    assert c.get(f'/api/ledger/{bid}').json()['trip'] is None
    assert c.get('/api/ledger').json()[0]['trip'] is None


@pytest.mark.parametrize('title',[None,'','  \n\t  ','omitted'])
def test_quick_entry_uses_category_without_typing(ctx,title):
    c,_,_=ctx;b=book(c);path=f'/api/ledger/{b}';data=body();data['category']='交通'
    if title=='omitted':data.pop('title')
    else:data['title']=title
    first=c.post(path+'/entries',json=data);assert first.status_code==200
    saved=first.json();assert saved['title']=='交通' and saved['amount_minor']==1234
    assert c.post(path+'/entries',json=data).json()==saved
    assert c.get(path).json()['count']==1
    data['category']='住宿';data['title']='';data['version']=saved['version']
    assert c.patch(path+'/entries/'+saved['id'],json=data).json()['title']=='住宿'
    data['title']='  海景酒店  ';data['version']+=1
    assert c.patch(path+'/entries/'+saved['id'],json=data).json()['title']=='海景酒店'


def test_book_title_still_required_and_default_category_title(ctx):
    c,_,_=ctx
    for data in ({},{'title':''},{'title':'  '}):assert c.post('/api/ledger',json=data).status_code==422
    b=book(c);data=body();data.pop('title');data.pop('category')
    r=c.post(f'/api/ledger/{b}/entries',json=data)
    assert r.status_code==200 and r.json()['title']=='其他'
