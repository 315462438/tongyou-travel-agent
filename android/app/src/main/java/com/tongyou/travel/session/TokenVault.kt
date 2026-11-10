package com.tongyou.travel.session

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Only ciphertext and a completed-migration marker are persisted. No token in Intents or logs. */
class TokenVault(context: Context) : SessionVault {
    private val prefs = context.getSharedPreferences("native_session", Context.MODE_PRIVATE)
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    @Synchronized override fun read(): String? {
        val encoded = prefs.getString("ciphertext", null) ?: return null
        return try {
            val parts = encoded.split(':')
            require(parts.size == 2) { "登录信息读取失败" }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)))
            String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), Charsets.UTF_8)
        } catch (e: Exception) {
            if (!permanent(e)) throw e
            // The key is gone or the stored value is not ours: retrying can never succeed. Drop the
            // ciphertext (the migration marker stays) so the user lands on the login screen.
            prefs.edit().remove("ciphertext").commit()
            null
        }
    }
    /** Wrong/lost key and malformed data never heal; other Keystore errors may be transient and are rethrown. */
    private fun permanent(e: Exception) = e is javax.crypto.AEADBadTagException || e is javax.crypto.BadPaddingException ||
        e is java.security.InvalidKeyException || e is java.security.UnrecoverableKeyException || e is IllegalArgumentException
    @Synchronized override fun save(token: String?) {
        val editor = prefs.edit().putBoolean("migrated", true)
        if (token.isNullOrEmpty()) editor.remove("ciphertext") else {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
            val ciphertext = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
            editor.putString("ciphertext", Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ciphertext, Base64.NO_WRAP))
        }
        check(editor.commit()) { "无法保存登录信息，请释放一些手机存储空间" }
    }
    override fun migrated() = prefs.getBoolean("migrated", false)
    companion object { private const val ALIAS = "tongyou.native.session.v1" }
}
