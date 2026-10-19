"""Independent ledger ACLs, invitations, capabilities, and concurrent-edit protection."""
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.db import models as m
from test_personal_ledger import ctx, body


def setup_book(ctx, role='viewer', accept=True):
    c,current,_=ctx
    bid=c.post('/api/ledger',json={'title':'共享旅行花费'}).json()['id']
    assert c.post(f'/api/ledger/{bid}/members',json={'username':'bob','role':role}).status_code==200
    current[0]='b'
    if accept: assert c.post(f'/api/ledger/{bid}/invites/respond',json={'accept':True}).status_code==200
    return c,current,bid


def test_pending_accept_decline_and_nontrip_access(ctx):
    c,current,bid=setup_book(ctx,'editor',False);path=f'/api/ledger/{bid}'
    assert c.get('/api/ledger').json()==[]
    assert c.get(path).status_code==404
    assert c.get('/api/ledger/invites/pending').json()==[{'id':bid,'title':'共享旅行花费','role':'editor','inviter':'alice'}]
    assert c.post(path+'/invites/respond',json={'accept':False}).status_code==200
    assert c.get(path).status_code==404
    current[0]='a';assert c.post(path+'/members',json={'username':'bob','role':'editor'}).status_code==200
    current[0]='b';assert c.post(path+'/invites/respond',json={'accept':True}).status_code==200
    assert c.get('/api/trips').json()==[]
    assert c.get(path).json()['role']=='editor'
    assert c.get('/api/ledger').json()[0]['id']==bid
    assert c.post(path+'/entries',json=body()).status_code==200
    current[0]='a';d=c.get(path).json();assert d['count']==1 and d['entries'][0]['created_by']=='b'


@pytest.mark.parametrize('role,allowed',[('editor',True),('viewer',False)])
def test_entry_role_matrix_and_owner_only_management(ctx,role,allowed):
    c,current,bid=setup_book(ctx,role);path=f'/api/ledger/{bid}'
    current[0]='a';eid=c.post(path+'/entries',json=body()).json()['id'];current[0]='b'
    assert c.get(path).status_code==200
    assert c.get(path+'/members').status_code==200
    expected=200 if allowed else 403
    assert c.post(path+'/entries',json=body()).status_code==expected
    assert c.patch(path+'/entries/'+eid,json=body()).status_code==expected
    assert c.delete(path+'/entries/'+eid).status_code==expected
    for method,suffix,data in [('PATCH','',{'title':'改名'}),('DELETE','',None),('PATCH','/currency',{'target_currency':'USD'}),('POST','/members',{'username':'alice','role':'editor'}),('PATCH','/members/a',{'role':'viewer'}),('DELETE','/members/a',None),('GET','/share',None),('POST','/share',{'role':'editor'}),('DELETE','/share',None)]:
        assert c.request(method,path+suffix,json=data).status_code==403


def test_permissions_removed_immediately_and_reinvite_required(ctx):
    c,current,bid=setup_book(ctx,'editor');path=f'/api/ledger/{bid}'
    entry=c.post(path+'/entries',json=body()).json()
    current[0]='a';link=c.post(path+'/share',json={'role':'editor'}).json()['token']
    assert c.patch(path+'/members/b',json={'role':'viewer'}).status_code==200
    current[0]='b'
    assert c.patch(path+'/entries/'+entry['id'],json=body()).status_code==403
    assert c.post('/api/ledger/join',json={'token':link}).status_code==200
    assert c.get(path).json()['role']=='viewer'  # link cannot upgrade
    current[0]='a';assert c.delete(path+'/members/b').status_code==200
    current[0]='b';assert c.get(path).status_code==404
    assert c.post('/api/ledger/join',json={'token':link}).status_code==403
    assert c.get('/api/ledger').json()==[]
    current[0]='a';assert c.get(path).json()['count']==1
    assert c.post(path+'/members',json={'username':'bob','role':'viewer'}).status_code==200
    current[0]='b';assert c.post(path+'/invites/respond',json={'accept':True}).status_code==200
    assert c.get(path).json()['role']=='viewer'


def test_share_preview_expiry_rotation_revocation(ctx):
    c,current,maker=ctx;bid=c.post('/api/ledger',json={'title':'限时账本'}).json()['id'];path=f'/api/ledger/{bid}'
    link=c.post(path+'/share',json={}).json();token=link['token']
    assert link['role']=='viewer' and len(token)>=32
    c.app.dependency_overrides.pop(__import__('app.api.deps',fromlist=['get_current_user']).get_current_user)
    preview=c.get('/api/ledger/shared/'+token)
    assert preview.status_code==200 and set(preview.json())=={'title','inviter','role','expires_at'}
    assert c.post('/api/ledger/join',json={'token':token}).status_code==401
    from app.api.deps import get_current_user
    def user():
        with maker() as db:return db.get(m.TravelUser,current[0])
    c.app.dependency_overrides[get_current_user]=user
    new=c.post(path+'/share',json={'role':'editor'}).json()['token'];assert new!=token
    assert c.get('/api/ledger/shared/'+token).status_code==404
    current[0]='b';assert c.post('/api/ledger/join',json={'token':new}).status_code==200
    assert c.get(path).json()['role']=='editor'
    current[0]='a';assert c.delete(path+'/share').status_code==200
    assert c.get('/api/ledger/shared/'+new).status_code==404
    current[0]='b';assert c.get(path).status_code==200
    current[0]='a';expired=c.post(path+'/share',json={}).json()['token']
    with maker() as db:db.get(m.TravelLedgerShare,bid).expires_at=m._now()-timedelta(seconds=1);db.commit()
    assert c.get('/api/ledger/shared/'+expired).status_code==404
    assert c.post('/api/ledger/join',json={'token':expired}).status_code==404
    assert c.get(path+'/share').json() is None


def test_trip_link_does_not_grant_trip_or_ledger_permissions(ctx):
    c,current,maker=ctx
    tid=c.post('/api/trips',json={'title':'私密路线','days':2}).json()['id']
    bid=c.post('/api/ledger',json={'title':'共同花费','trip_id':tid}).json()['id'];path=f'/api/ledger/{bid}'
    c.post(path+'/members',json={'username':'bob','role':'editor'});current[0]='b';c.post(path+'/invites/respond',json={'accept':True})
    assert c.get(path).json()['trip'] is None
    assert c.get('/api/trips/'+tid).status_code==404
    assert c.patch(path,json={'title':'偷关联','trip_id':tid}).status_code==403
    with maker() as db:db.add(m.TravelTripMember(trip_id=tid,user_id='b',role='editor',status='accepted'));db.commit()
    assert c.get(path).json()['trip']['id']==tid
    assert c.post('/api/trips/'+tid+'/leave').status_code==200
    assert c.get(path).json()['role']=='editor'
    assert c.get(path).json()['trip'] is None
    current[0]='a';c.delete('/api/trips/'+tid)
    assert c.get(path).json()['trip'] is None
    current[0]='b';assert c.get(path).status_code==200


def test_version_conflicts_idempotent_retry_and_exit(ctx):
    c,current,bid=setup_book(ctx,'editor');path=f'/api/ledger/{bid}';data=body()
    e=c.post(path+'/entries',json=data).json();assert e['version']==1
    assert c.post(path+'/entries',json=data).json()==e
    data['version']=1;data['amount']='20.00'
    assert c.patch(path+'/entries/'+e['id'],json=data).json()['version']==2
    assert c.patch(path+'/entries/'+e['id'],json=data).status_code==409
    assert c.delete(path+'/entries/'+e['id'],params={'version':1}).status_code==409
    assert c.post(path+'/leave').status_code==200
    assert c.get(path).status_code==404
    current[0]='a';assert c.get(path).json()['count']==1
    assert c.post(path+'/leave').status_code==403
    assert c.delete(path+'/entries/'+e['id'],params={'version':2}).status_code==200


def test_no_owner_grant_or_crossbook_member_mutation_and_cleanup(ctx):
    c,current,maker=ctx;c,current,bid=setup_book(ctx,'viewer');path=f'/api/ledger/{bid}'
    current[0]='a'
    assert c.patch(path+'/members/a',json={'role':'viewer'}).status_code==404
    assert c.delete(path+'/members/a').status_code==404
    assert c.post(path+'/members',json={'username':'bob','role':'owner'}).status_code==422
    assert c.post(path+'/share',json={'role':'owner'}).status_code==422
    assert c.post(path+'/members',json={'username':'bob','role':'editor'}).status_code==200
    assert c.get(path+'/members').json()[1]['role']=='viewer'
    c.post(path+'/share',json={});assert c.delete(path).status_code==200
    with maker() as db:
        assert db.get(m.TravelLedgerShare,bid) is None
        assert not db.scalars(select(m.TravelLedgerMember).where(m.TravelLedgerMember.ledger_id==bid)).all()
    current[0]='b';assert c.get(path).status_code==404


def test_pending_invite_role_takes_precedence_over_link(ctx):
    c,current,bid=setup_book(ctx,'viewer',False);path=f'/api/ledger/{bid}'
    current[0]='a';token=c.post(path+'/share',json={'role':'editor'}).json()['token'];current[0]='b'
    assert c.post('/api/ledger/join',json={'token':token}).status_code==200
    assert c.get(path).json()['role']=='viewer'


def test_member_cap(ctx):
    c,_,maker=ctx;bid=c.post('/api/ledger',json={'title':'满员'}).json()['id']
    with maker() as db:
        db.add_all(m.TravelLedgerMember(ledger_id=bid,user_id=str(n),role='viewer',status='pending') for n in range(49));db.commit()
    assert c.post(f'/api/ledger/{bid}/members',json={'username':'bob'}).status_code==409
