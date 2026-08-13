"""Action Guard 测试 —— 对应 docs/test_cases 用例 4、5"""

from app.tools.action_guard import Decision, judge_action, judge_page_type


class TestReadOnlyActions:
    """用例 5：普通页面 navigate + snapshot 全部 ALLOW，无误报"""

    def test_navigate_always_allowed(self):
        # 即使 URL 里有敏感词，navigate 也放行（落地后由第三层页面检测处置）
        r = judge_action("navigate", url="https://example.com/login")
        assert r.decision == Decision.ALLOW

    def test_snapshot_allowed(self):
        assert judge_action("snapshot").decision == Decision.ALLOW

    def test_screenshot_allowed(self):
        assert judge_action("screenshot").decision == Decision.ALLOW

    def test_scroll_allowed(self):
        assert judge_action("scroll").decision == Decision.ALLOW


class TestNoFalsePositives:
    """核心修正：整页含敏感词不影响正常元素点击"""

    def test_click_normal_element_on_page_with_login_header(self):
        # 页面上有登录按钮，但点击的是"查看酒店详情"——不应误报
        r = judge_action(
            "click",
            target_text="查看酒店详情",
            target_href="/hotel/12345",
            url="https://booking.example.com/search?q=tokyo",
        )
        assert r.decision == Decision.ALLOW

    def test_click_next_page(self):
        r = judge_action("click", target_text="下一页", url="https://example.com/hotels")
        assert r.decision == Decision.ALLOW


class TestHighRisk:
    """用例 4：含「立即支付」按钮的点击请求 → BLOCK"""

    def test_click_pay_button_blocked(self):
        r = judge_action("click", target_text="立即支付", url="https://example.com/hotel/1")
        assert r.decision == Decision.BLOCK
        assert r.risk_level == "high"

    def test_click_checkout_href_blocked(self):
        r = judge_action(
            "click", target_text="继续", target_href="https://example.com/checkout/step1"
        )
        assert r.decision == Decision.BLOCK

    def test_click_place_order_blocked(self):
        r = judge_action("click", target_text="Place Order")
        assert r.decision == Decision.BLOCK


class TestMediumRisk:
    def test_click_login_button_handoff(self):
        r = judge_action("click", target_text="登录", url="https://example.com")
        assert r.decision == Decision.REQUIRE_HANDOFF

    def test_fill_phone_field_handoff(self):
        r = judge_action("fill", target_text="请输入手机号")
        assert r.decision == Decision.REQUIRE_HANDOFF

    def test_click_login_href_handoff(self):
        r = judge_action("click", target_text="继续", target_href="/passport/login")
        assert r.decision == Decision.REQUIRE_HANDOFF

    def test_qr_toggle_whitelisted(self):
        """「扫码登录」tab 只切换登录框展示形态（把二维码翻给用户扫），精确白名单放行。"""
        assert judge_action("click", target_text="扫码登录").decision == Decision.ALLOW
        assert judge_action("click", target_text="二维码登录").decision == Decision.ALLOW

    def test_qr_toggle_whitelist_is_exact(self):
        """白名单必须精确匹配：带其他动作语义的文本不放行；fill 不放行。"""
        assert judge_action("click", target_text="扫码登录并绑定").decision == Decision.REQUIRE_HANDOFF
        assert judge_action("fill", target_text="扫码登录").decision == Decision.REQUIRE_HANDOFF


class TestPageTypeDisposition:
    """用例 3：登录墙页面 → need_user_handoff"""

    def test_login_wall_handoff(self):
        assert judge_page_type("login_wall").decision == Decision.REQUIRE_HANDOFF

    def test_captcha_handoff(self):
        assert judge_page_type("captcha").decision == Decision.REQUIRE_HANDOFF

    def test_payment_blocked(self):
        assert judge_page_type("payment").decision == Decision.BLOCK

    def test_content_allowed(self):
        assert judge_page_type("content").decision == Decision.ALLOW
        assert judge_page_type("hotel").decision == Decision.ALLOW


class TestUnknownAction:
    def test_unknown_action_blocked(self):
        assert judge_action("execute_script_evil").decision == Decision.BLOCK
