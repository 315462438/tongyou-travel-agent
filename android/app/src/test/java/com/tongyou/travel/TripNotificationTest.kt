package com.tongyou.travel

import com.tongyou.travel.data.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class TripNotificationTest {
    private fun poll(id: String, day: Int?, waiting: Boolean = true) = buildJsonObject {
        put("id", id); put("day", day?.let(::JsonPrimitive) ?: JsonNull)
        put("closed", false); put("my_vote", if (waiting) JsonNull else JsonPrimitive(0))
    }
    @Test fun notificationParsingAndRoute() {
        val notice = Json.parseToJsonElement("""{"type":"trip_poll","target_kind":"trip","target_id":"fallback","meta":{"trip_id":"t1","poll_id":"p2","day":2}}""").jsonObject
        val target = TripNotification.from(notice)!!
        assertEquals(TripNotification("t1", 2, "p2"), target)
        assertEquals("trip/t1?notification=poll&day=2&poll=p2", target.route())
        assertTrue(TripNotification("a/b", null, "p &q").route().contains("trip/a%2Fb?notification=poll&day=0&poll=p%20%26q"))
        assertNull(TripNotification.from(JsonObject(notice + ("type" to JsonPrimitive("trip_chat")))))
        assertEquals("fallback", TripNotification.from(JsonObject(notice + ("meta" to buildJsonObject { put("day", -1) })))?.tripId)
        assertNull(TripNotification.from(JsonObject(notice + ("meta" to buildJsonObject { put("day", 1.5) })))?.day)
    }
    @Test fun preferCurrentPollDayAndFallbackSafely() {
        val target = TripNotification("t", 2, "p")
        assertEquals(3 to "p", target.resolve(3, listOf(poll("p", 3))))
        assertEquals(1 to "p", target.resolve(3, listOf(poll("p", null))))
        assertEquals(2 to null, target.resolve(3, emptyList()))
        assertEquals(1 to null, target.resolve(1, listOf(poll("p", 2))))
        assertEquals(1 to null, target.resolve(0, emptyList(), 99))
        assertEquals(2 to "p", TripNotification("t", null, "p").resolve(3, listOf(poll("p", 2))))
    }
    @Test fun scrollIndexAccountsForOptionalRowsAndGlobalPolls() {
        val polls = listOf(poll("global", null), poll("day1", 1), poll("day2a", 2), poll("day2b", 2))
        assertEquals(2, notificationPollIndex(polls, 2, "global", false, false, false))
        assertEquals(5, notificationPollIndex(polls, 2, "day2a", false, false, false))
        assertEquals(9, notificationPollIndex(polls, 2, "day2b", true, true, true))
        assertNull(notificationPollIndex(polls, 1, "day2a", false, false, false))
        assertEquals(1, notificationPollIndex(listOf(poll("global", null, false)), 2, "global", false, false, false))
    }
}
