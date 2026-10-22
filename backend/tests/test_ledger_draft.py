"""一句话记账：草稿归一（币种默认链、日期、金额、分类）、接口权限、批量入账的原子性与幂等。"""
import uuid
from datetime import date

import pytest

from app.agent import ledger_draft as ld
from app.api import ledger_api
from app.db import models as m
from test_personal_ledger import ctx  # noqa: F401
from test_ledger_collaboration import setup_book

TODAY = date(2026, 10, 22)


def items(*rows):
    return ld.DraftExtraction(items=[ld.DraftItem(**row) for row in rows])


def norm(extraction, text='', destination=None, recent=()):
    return ld.normalize(extraction, text=text, today=TODAY, destination=destination, recent=list(recent))


def test_currency_and_category_sets_match_ledger():
    assert set(ld.CURRENCIES) == ledger_api.CURRENCIES
    assert set(ld.CATEGORIES) == ledger_api.CATEGORIES


def test_japan_trip_splits_items_with_trip_currency():
    out = norm(items(dict(title='拉面', amount='1200', currency='JPY', category='餐饮'),
                     dict(title='打车', amount='2800', category='交通'),
                     dict(title='药妆', amount='12000', category='购物')),
               text='午饭拉面1200日元，打车2800，药妆一万二', destination='东京·大阪 5 日')
    assert [(i['title'], i['amount'], i['currency'], i['category']) for i in out.items] == [
        ('拉面', '1200.00', 'JPY', '餐饮'), ('打车', '2800.00', 'JPY', '交通'), ('药妆', '12000.00', 'JPY', '购物')]
    assert out.currency_source == 'trip' and not any(i['currency_guessed'] for i in out.items)
    assert len({i['id'] for i in out.items}) == 3


def test_yen_symbol_in_japan_trip_is_flagged():
    out = norm(items(dict(title='饮料', amount='300', category='餐饮')), text='饮料¥300', destination='京都')
    assert out.items[0]['currency'] == 'JPY' and out.items[0]['currency_guessed'] is True


def test_default_chain_history_then_fallback():
    assert ld.default_currency(None, ['THB', 'THB', 'CNY']) == ('THB', 'history')
    assert ld.default_currency('杭州周末', []) == ('CNY', 'fallback')
    assert ld.default_currency('仙本那潜水', ['CNY']) == ('MYR', 'trip')
    fresh = norm(items(dict(title='午饭', amount='50', category='餐饮')), text='午饭 50')
    assert fresh.items[0]['currency'] == 'CNY' and fresh.items[0]['currency_guessed'] is True
    said_yuan = norm(items(dict(title='午饭', amount='50', category='餐饮')), text='午饭 50 元')
    assert said_yuan.items[0]['currency_guessed'] is False


def test_dates_resolved_on_server():
    assert ld.resolve_day('yesterday', TODAY) == date(2026, 10, 21)
    assert ld.resolve_day('day_before', TODAY) == date(2026, 10, 20)
    assert ld.resolve_day('2026-10-19', TODAY) == date(2026, 10, 19)
    assert ld.resolve_day('2026-10-30', TODAY) == TODAY, 'future dates fall back to today'
    assert ld.resolve_day('不知道', TODAY) == TODAY


def test_amounts_bad_values_and_unknown_category():
    assert ld.parse_amount('1,200') == ld.Decimal('1200.00')
    assert ld.parse_amount('约 35.5 元') == ld.Decimal('35.50')
    for bad in ('', '免费', '0', '-5', '99999999'):
        assert ld.parse_amount(bad) is None
    out = norm(items(dict(title='', amount='免费', category='餐饮'), dict(title='', amount='88', category='娱乐', currency='xyz')))
    assert out.dropped == 1 and len(out.items) == 1
    assert out.items[0]['category'] == '其他' and out.items[0]['title'] == '其他' and out.items[0]['currency'] == 'CNY'


class FakeLLM:
    def __init__(self, result): self.result = result; self.prompts = []
    def parse(self, prompt, schema, **kwargs):
        self.prompts.append((prompt, kwargs)); return self.result


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM(items(dict(title='拉面', amount='1200', category='餐饮'), dict(title='打车', amount='2800', category='交通')))
    monkeypatch.setattr('app.llm.client.get_llm', lambda: llm)
    return llm


def test_draft_endpoint_uses_trip_destination_and_writes_nothing(ctx, fake_llm):
    c, current, maker = ctx
    with maker() as db:
        db.add(m.TravelTrip(id='t1', owner_id='a', title='关西慢游', destination='大阪'))
        db.add(m.TravelTripMember(trip_id='t1', user_id='a', role='owner', status='accepted')); db.commit()
    bid = c.post('/api/ledger', json={'title': '关西', 'trip_id': 't1'}).json()['id']
    res = c.post(f'/api/ledger/{bid}/ai-draft', json={'text': '拉面1200 打车2800', 'today': '2026-10-22'})
    assert res.status_code == 200, res.text
    data = res.json()
    assert [d['currency'] for d in data['drafts']] == ['JPY', 'JPY'] and data['currency_source'] == 'trip'
    assert '今天是' in fake_llm.prompts[0][0] and fake_llm.prompts[0][1]['effort'] == 'low'
    assert c.get(f'/api/ledger/{bid}').json()['count'] == 0, 'drafts are not saved'


def test_draft_endpoint_rejects_viewers_and_empty_results(ctx, fake_llm):
    c, current, bid = setup_book(ctx, 'viewer')
    assert c.post(f'/api/ledger/{bid}/ai-draft', json={'text': '午饭 50'}).status_code == 403
    current[0] = 'a'
    fake_llm.result = items()
    res = c.post(f'/api/ledger/{bid}/ai-draft', json={'text': '今天很开心'})
    assert res.status_code == 422 and '没认出金额' in res.json()['detail']


def entry(**over):
    return {'id': str(uuid.uuid4()), 'title': '拉面', 'amount': '1200.00', 'currency': 'JPY', 'category': '餐饮', 'spent_at': '2026-10-22', 'note': '', **over}


def test_batch_commit_is_atomic_and_idempotent(ctx):
    c, current, _ = ctx
    bid = c.post('/api/ledger', json={'title': '关西'}).json()['id']
    batch = [entry(), entry(title='打车', amount='2800.00', category='交通')]
    first = c.post(f'/api/ledger/{bid}/entries/batch', json={'entries': batch})
    assert first.status_code == 200 and len(first.json()['entries']) == 2
    again = c.post(f'/api/ledger/{bid}/entries/batch', json={'entries': batch})
    assert again.status_code == 200 and c.get(f'/api/ledger/{bid}').json()['count'] == 2, 'double confirm saves once'
    bad = c.post(f'/api/ledger/{bid}/entries/batch', json={'entries': [entry(), entry(currency='XXX')]})
    assert bad.status_code == 422 and c.get(f'/api/ledger/{bid}').json()['count'] == 2, 'one invalid row saves nothing'
    changed = dict(batch[0], amount='999.00')
    assert c.post(f'/api/ledger/{bid}/entries/batch', json={'entries': [entry(), changed]}).status_code == 409
    assert c.get(f'/api/ledger/{bid}').json()['count'] == 2


def test_batch_commit_requires_edit_role(ctx):
    c, current, bid = setup_book(ctx, 'viewer')
    assert c.post(f'/api/ledger/{bid}/entries/batch', json={'entries': [entry()]}).status_code == 403
