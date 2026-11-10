package com.tongyou.travel

import com.tongyou.travel.ui.*
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate

/** Input rules behind the native ledger and trip screens. */
class NativeScreensLogicTest {
    @Test fun ledgerAmountFollowsTheServerRule() {
        assertEquals("12.5", validLedgerAmount(" 12.5 "))
        assertEquals("1200", validLedgerAmount("1200"))
        assertEquals("0.01", validLedgerAmount("0,01"))                // 小数逗号按点处理
        for (bad in listOf("", "0", "0.00", "-3", "1.234", "12345678", "abc", "1e3", "1.")) assertNull(bad, validLedgerAmount(bad))
    }
    @Test fun moneyAlwaysShowsTwoDecimalsAndNeverLocaleCommas() {
        assertEquals("MYR 35.00", ledgerMoney(3500, "MYR"))
        assertEquals("CNY 0.05", ledgerMoney(5, "CNY"))
        assertEquals("JPY 123456.70", ledgerMoney(12345670, "JPY"))
    }
    @Test fun tripDateAcceptsWhatPeopleType() {
        val today = LocalDate.of(2026, 11, 10)
        assertEquals("2026-11-20", parseTripDate("11.20", today))
        assertEquals("2026-11-20", parseTripDate("11月20日", today))
        assertEquals("2026-11-20", parseTripDate("11/20", today))
        assertEquals("2027-01-03", parseTripDate("2027-1-3", today))
        assertEquals("2027-01-03", parseTripDate("27.1.3", today))
        for (bad in listOf("", "明天", "13.40", "2.30", "20")) assertNull(bad, parseTripDate(bad, today))
    }
    @Test fun rolesReadAsWords() {
        assertEquals("创建者", ledgerRole("owner")); assertEquals("可编辑", ledgerRole("editor")); assertEquals("只读", ledgerRole("viewer"))
    }
}

class InviteLinkTest {
    @Test fun recognisesEveryShareFormat() {
        val ledger = "a".repeat(43)
        org.junit.Assert.assertEquals(com.tongyou.travel.data.InviteLink.TripCode("ab12cd34"), com.tongyou.travel.data.parseInviteLink("https://17tongyou.com/t/AB12cd34"))
        org.junit.Assert.assertEquals(com.tongyou.travel.data.InviteLink.TripToken("tok_en-123456"), com.tongyou.travel.data.parseInviteLink("https://17tongyou.com/travel/?join=tok_en-123456"))
        org.junit.Assert.assertEquals(com.tongyou.travel.data.InviteLink.Ledger(ledger), com.tongyou.travel.data.parseInviteLink("https://17tongyou.com/travel/?ledger_join=$ledger"))
        org.junit.Assert.assertEquals(com.tongyou.travel.data.InviteLink.Home, com.tongyou.travel.data.parseInviteLink("https://17tongyou.com/travel/"))
    }
    @Test fun rejectsOtherHostsSchemesAndMalformedTokens() {
        for (bad in listOf("http://17tongyou.com/t/ab12cd34", "https://17tongyou.com.evil.example/t/ab12cd34", "https://evil.example/travel/?join=abcdefgh",
                           "https://17tongyou.com/other/?join=abcdefgh", "https://17tongyou.com/travel/?ledger_join=short", "not a url"))
            org.junit.Assert.assertTrue(bad, com.tongyou.travel.data.parseInviteLink(bad).let { it == null || it == com.tongyou.travel.data.InviteLink.Home })
    }
}
