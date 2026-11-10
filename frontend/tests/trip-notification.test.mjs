import test from 'node:test'
import assert from 'node:assert/strict'
import {tripNotificationTarget, resolvePollNotification} from '../src/tripNotification.ts'

const notification = (meta = {}) => ({type:'trip_poll',target_kind:'trip',target_id:'fallback',meta})
test('trip notification keeps identity and distinguishes chat, poll and ordinary trip', () => {
  const target=tripNotificationTarget(notification({trip_id:'t1',poll_id:'p2',day:2}),1)
  assert.deepEqual(target,{tripId:'t1',pollId:'p2',day:2,kind:'poll',requestId:1})
  assert.equal(tripNotificationTarget(notification(),2).tripId,'fallback')
  assert.equal(tripNotificationTarget({...notification(),type:'trip_chat'},3).kind,'chat')
  assert.equal(tripNotificationTarget({...notification(),type:'trip_update'},4).kind,'trip')
  assert.equal(tripNotificationTarget({...notification(),target_kind:'friends'},5),null)
  assert.equal(tripNotificationTarget({...notification(),target_id:''},6),null)
  assert.notDeepEqual(target,tripNotificationTarget(notification({trip_id:'t1',poll_id:'p2',day:2}),7))
})
test('malformed notification days never select an invalid day', () => {
  for(const day of [0,-1,1.5,'2',NaN,Infinity,{},null]) assert.equal(tripNotificationTarget(notification({day}),1).day,null)
  assert.equal(resolvePollNotification({day:99,pollId:null},3,[],2).day,2)
  assert.equal(resolvePollNotification({day:99,pollId:null},0,[],99).day,1)
})
test('current poll day wins, including whole-trip votes and old notifications', () => {
  const target={day:2,pollId:'p'}
  assert.deepEqual(resolvePollNotification(target,3,[{id:'p',day:3}]),{day:3,pollId:'p'})
  assert.deepEqual(resolvePollNotification(target,3,[{id:'p',day:null}],1),{day:1,pollId:'p'})
  assert.deepEqual(resolvePollNotification({day:null,pollId:'p'},3,[{id:'p',day:2}]),{day:2,pollId:'p'})
  assert.deepEqual(resolvePollNotification(target,3,[]),{day:2,pollId:null})
  assert.deepEqual(resolvePollNotification(target,1,[{id:'p',day:2}]),{day:1,pollId:null})
})
