package com.tongyou.travel.chat

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.*
import android.os.Bundle
import android.os.Looper
import kotlinx.coroutines.*
import kotlin.coroutines.resume

/** Coarse WGS-84 only, at the user's nearby request. Never cached or persisted. */
@SuppressLint("MissingPermission")
suspend fun nearbyLocation(context: Context): String = withContext(Dispatchers.Main) {
    if (context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) return@withContext ""
    val manager = context.getSystemService(LocationManager::class.java)
    var listener: LocationListener? = null
    try {
        withTimeoutOrNull(5000) {
            suspendCancellableCoroutine { continuation ->
                listener = object : LocationListener {
                    override fun onLocationChanged(location: Location) {
                        if (continuation.isActive) continuation.resume("${location.longitude},${location.latitude}")
                    }
                    override fun onProviderDisabled(provider: String) { if (continuation.isActive) continuation.resume("") }
                    override fun onProviderEnabled(provider: String) {}
                    @Deprecated("Required for API 26") override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
                }
                if (!manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) continuation.resume("")
                else manager.requestSingleUpdate(LocationManager.NETWORK_PROVIDER, listener!!, Looper.getMainLooper())
            }
        }.orEmpty()
    } catch (_: SecurityException) { "" } catch (_: IllegalArgumentException) { "" }
    finally { listener?.let(manager::removeUpdates) }
}
