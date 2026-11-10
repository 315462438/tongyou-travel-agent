package com.tongyou.travel.data

/** What a shared 17同游 link asks the app to do. Parsing is pure so it can be tested off-device. */
sealed interface InviteLink {
    data class TripToken(val token: String) : InviteLink
    data class TripCode(val code: String) : InviteLink
    data class Ledger(val token: String) : InviteLink
    data object Home : InviteLink
}

fun parseInviteLink(url: String): InviteLink? {
    val uri = runCatching { java.net.URI(url.trim()) }.getOrNull() ?: return null
    if (uri.scheme != "https" || uri.host != "17tongyou.com") return null
    val path = uri.path.orEmpty()
    Regex("^/t/([A-Za-z0-9_-]{6,32})/?$").find(path)?.let { return InviteLink.TripCode(it.groupValues[1].lowercase()) }
    if (path != "/travel" && path != "/travel/") return null
    val query = uri.rawQuery.orEmpty().split('&').mapNotNull { part ->
        part.split('=', limit = 2).takeIf { it.size == 2 }?.let { it[0] to java.net.URLDecoder.decode(it[1], "UTF-8") }
    }.toMap()
    query["ledger_join"]?.takeIf { Regex("^[A-Za-z0-9_-]{32,64}$").matches(it) }?.let { return InviteLink.Ledger(it) }
    query["join"]?.takeIf { Regex("^[A-Za-z0-9_-]{8,64}$").matches(it) }?.let { return InviteLink.TripToken(it) }
    return InviteLink.Home
}

/** Resolves and accepts an invite. Returns the route to open: "trip/<id>", "ledger/<id>" or "home". */
suspend fun acceptInvite(api: TravelService, link: InviteLink): String = when (link) {
    InviteLink.Home -> "home"
    is InviteLink.Ledger -> "ledger/" + api.request("POST", "ledger/join", jsonBody("token" to link.token)).obj()["id"].string()
    is InviteLink.TripToken -> "trip/" + api.request("POST", "trips/join", jsonBody("token" to link.token)).obj()["trip_id"].string()
    is InviteLink.TripCode -> {
        val target = api.redirect("trips/t/${link.code}") ?: throw ApiFailure(404, "链接无效或已被关闭")
        val token = (parseInviteLink(if (target.startsWith("/")) "https://17tongyou.com$target" else target) as? InviteLink.TripToken)?.token
            ?: throw ApiFailure(404, "链接无效或已被关闭")
        acceptInvite(api, InviteLink.TripToken(token))
    }
}
