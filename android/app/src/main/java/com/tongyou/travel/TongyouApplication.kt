package com.tongyou.travel

import android.app.Application
import com.tongyou.travel.data.TravelApi
import com.tongyou.travel.data.TravelService
import com.tongyou.travel.data.SessionService
import com.tongyou.travel.session.Session
import com.tongyou.travel.session.TokenVault

class TongyouApplication : Application() {
    val session by lazy { Session(this, TokenVault(this)) }
    var service: TravelService = TravelApi({ session.token() }, { session.invalidate(it) })
    fun scopedService(expectedToken: String): TravelService {
        // Capture the credential: an old chat cannot borrow a later account's token.
        val delegate = if (service is TravelApi) TravelApi({ expectedToken }, { session.invalidate(it) }) else service
        return SessionService(delegate, expectedToken, session::token)
    }
}
