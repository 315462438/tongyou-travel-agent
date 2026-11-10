package com.tongyou.travel.data

import kotlinx.serialization.json.*
import java.net.URLEncoder

data class TripNotification(val tripId: String, val day: Int?, val pollId: String?) {
    fun route(): String = "trip/${encode(tripId)}?notification=poll&day=${day ?: 0}&poll=${encode(pollId.orEmpty())}"
    fun resolve(days: Int, polls: List<JsonObject>, currentDay: Int = 1): Pair<Int, String?> {
        val poll = polls.firstOrNull { it["id"].string() == pollId }
        val wanted = if (poll != null) (poll["day"] as? JsonPrimitive)?.intOrNull else day
        val selected = wanted?.takeIf { it in 1..days } ?: currentDay.takeIf { it in 1..days } ?: 1
        val pollDay = (poll?.get("day") as? JsonPrimitive)?.intOrNull
        return selected to poll?.takeIf { pollDay == null || pollDay == selected }?.get("id")?.string()
    }
    companion object {
        private fun encode(value: String) = URLEncoder.encode(value, "UTF-8").replace("+", "%20")
        fun from(notice: JsonObject): TripNotification? {
            if (notice["type"].string() != "trip_poll" || notice["target_kind"].string() != "trip") return null
            val meta = notice["meta"]?.obj().orEmpty()
            val id = meta["trip_id"].string().trim().ifBlank { notice["target_id"].string().trim() }
            if (id.isBlank()) return null
            return TripNotification(id, (meta["day"] as? JsonPrimitive)?.intOrNull?.takeIf { it > 0 }, meta["poll_id"].string().trim().ifBlank { null })
        }
    }
}

/** Index of the poll in the detail list: header, optional notices, global polls, day header/map, daily polls. */
fun notificationPollIndex(polls: List<JsonObject>, day: Int, pollId: String, hasError: Boolean, askDate: Boolean, hasDayTitle: Boolean): Int? {
    val global = polls.filter { it["day"] == null || it["day"] is JsonNull }
    val daily = polls.filter { (it["day"] as? JsonPrimitive)?.intOrNull == day }
    val waiting = polls.any { !it["closed"].bool() && it["my_vote"] is JsonNull }
    val prefix = 1 + listOf(hasError, askDate, waiting).count { it }
    val globalIndex = global.indexOfFirst { it["id"].string() == pollId }
    if (globalIndex >= 0) return prefix + globalIndex
    val dailyIndex = daily.indexOfFirst { it["id"].string() == pollId }
    return dailyIndex.takeIf { it >= 0 }?.let { prefix + global.size + 2 + (if (hasDayTitle) 1 else 0) + it }
}
