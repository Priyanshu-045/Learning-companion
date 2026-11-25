package com.example.companion.data

import android.content.Context
import android.os.StatFs
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest

data class ModelResolution(
    val ready: Boolean,
    val modelFile: File,
    val tokenizerFile: File,
    val statusMessage: String,
    val availableBytes: Long = 0L,
    val verifiedSha256: String? = null
)

/**
 * Manages production app-specific storage for ExecuTorch Llama 3.2 1B model and tokenizer.
 * Uses Android's private internal storage ([Context.filesDir]) and optional app-specific external
 * staging ([Context.getExternalFilesDir]) without depending on temporary ADB paths.
 */
class ModelStorage(private val context: Context) {

    companion object {
        private const val TAG = "ModelStorage"
        const val MODEL_SUBDIR = "models/llama3_2_1b"
        const val MODEL_FILENAME = "Llama-3.2-1B-Instruct-SpinQuant_INT4_EO8.pte"
        const val QNN_MODEL_FILENAME = "Llama-3.2-1B-Instruct-QNN_HTP.pte"
        const val TOKENIZER_FILENAME = "tokenizer.model"
        private const val META_FILENAME = ".verified.json"

        const val EXPECTED_MODEL_SIZE_BYTES = 1_135_951_488L
        const val EXPECTED_MODEL_SHA256 = "8715cdba9e91f6bede00cc5f2d6b12397b95225da5630c4972a8da03001cda3b"

        const val EXPECTED_TOKENIZER_SIZE_BYTES = 2_183_982L
        const val EXPECTED_TOKENIZER_SHA256 = "82e9d31979e92ab929cd544440f129d9ecd797b69e327f80f17e1c50d5551b55"

        private const val STORAGE_SAFETY_MARGIN_BYTES = 100L * 1024L * 1024L
        private const val STREAM_BUFFER_SIZE = 64 * 1024

        internal fun sha256OfFile(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(STREAM_BUFFER_SIZE)
            FileInputStream(file).use { input ->
                while (true) {
                    val read = input.read(buffer)
                    if (read <= 0) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        internal fun streamCopyAndHash(source: File, destTemp: File): Pair<Long, String> {
            val digest = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(STREAM_BUFFER_SIZE)
            var totalBytes = 0L
            FileInputStream(source).use { input ->
                FileOutputStream(destTemp).use { output ->
                    while (true) {
                        val read = input.read(buffer)
                        if (read <= 0) break
                        digest.update(buffer, 0, read)
                        output.write(buffer, 0, read)
                        totalBytes += read
                    }
                    output.fd.sync()
                }
            }
            val hex = digest.digest().joinToString("") { "%02x".format(it) }
            return totalBytes to hex
        }
    }

    val productionDir: File
        get() = File(context.filesDir, MODEL_SUBDIR)

    val productionModelFile: File
        get() = File(productionDir, MODEL_FILENAME)

    val qnnModelFile: File
        get() = File(productionDir, QNN_MODEL_FILENAME)

    val activeModelFile: File
        get() = if (qnnModelFile.exists()) qnnModelFile else productionModelFile

    val productionTokenizerFile: File
        get() = File(productionDir, TOKENIZER_FILENAME)

    private val metaFile: File
        get() = File(productionDir, META_FILENAME)

    fun availableStorageBytes(dir: File = productionDir): Long {
        val target = if (dir.exists()) dir else context.filesDir
        return try {
            StatFs(target.absolutePath).availableBytes
        } catch (e: Exception) {
            0L
        }
    }

    /**
     * Resolves and verifies model + tokenizer in app-specific storage.
     * Must NOT be called on the Android main thread (streams up to 1.1 GB on first verification).
     */
    fun resolveAndVerify(forceChecksum: Boolean = false, cleanStagedAfterImport: Boolean = true): ModelResolution {
        val prodDir = productionDir
        if (!prodDir.exists()) {
            prodDir.mkdirs()
        }
        val avail = availableStorageBytes(prodDir)
        val model = productionModelFile
        val tokenizer = productionTokenizerFile

        // 1. Check already-installed production files
        if (model.exists() && tokenizer.exists()) {
            if (model.length() == EXPECTED_MODEL_SIZE_BYTES && tokenizer.length() == EXPECTED_TOKENIZER_SIZE_BYTES) {
                if (!forceChecksum && hasValidVerificationReceipt(model, tokenizer)) {
                    Log.i(TAG, "Verified cached production model at ${model.absolutePath} (${model.length()} bytes)")
                    return ModelResolution(
                        ready = true,
                        modelFile = model,
                        tokenizerFile = tokenizer,
                        statusMessage = "Production model verified (cached SHA-256 receipt)",
                        availableBytes = avail,
                        verifiedSha256 = EXPECTED_MODEL_SHA256
                    )
                }

                // Perform full streaming SHA-256 verification (64 KB buffer, zero heap bloat)
                val tokHash = sha256OfFile(tokenizer)
                if (tokHash != EXPECTED_TOKENIZER_SHA256) {
                    Log.w(TAG, "Tokenizer SHA-256 mismatch: $tokHash != $EXPECTED_TOKENIZER_SHA256")
                    tokenizer.delete()
                } else {
                    val modHash = sha256OfFile(model)
                    if (modHash == EXPECTED_MODEL_SHA256) {
                        writeVerificationReceipt(model, tokenizer)
                        Log.i(TAG, "Verified production model SHA-256 at ${model.absolutePath}")
                        return ModelResolution(
                            ready = true,
                            modelFile = model,
                            tokenizerFile = tokenizer,
                            statusMessage = "Production model and tokenizer SHA-256 verified",
                            availableBytes = avail,
                            verifiedSha256 = modHash
                        )
                    } else {
                        Log.w(TAG, "Model SHA-256 mismatch: $modHash != $EXPECTED_MODEL_SHA256")
                        model.delete()
                    }
                }
            } else {
                Log.w(
                    TAG,
                    "Incomplete production files (model=${model.length()}/$EXPECTED_MODEL_SIZE_BYTES, " +
                        "tokenizer=${tokenizer.length()}/$EXPECTED_TOKENIZER_SIZE_BYTES). Cleaning incomplete artifacts."
                )
                if (model.exists() && model.length() != EXPECTED_MODEL_SIZE_BYTES) model.delete()
                if (tokenizer.exists() && tokenizer.length() != EXPECTED_TOKENIZER_SIZE_BYTES) tokenizer.delete()
                metaFile.delete()
            }
        }

        // 2. Import from app-specific external staging directory if staged files exist
        val stagedBase = context.getExternalFilesDir("models")
        val stagedDir = if (stagedBase != null) File(stagedBase, "llama3_2_1b") else null
        if (stagedDir != null && stagedDir.exists()) {
            val stagedModel = File(stagedDir, MODEL_FILENAME)
            val stagedTok = File(stagedDir, TOKENIZER_FILENAME)
            if (stagedModel.exists() && stagedTok.exists()) {
                val needed = (if (model.exists()) 0L else stagedModel.length()) +
                    (if (tokenizer.exists()) 0L else stagedTok.length()) +
                    STORAGE_SAFETY_MARGIN_BYTES
                val currentAvail = availableStorageBytes(prodDir)
                if (currentAvail < needed) {
                    val msg = "Insufficient storage to provision model: available=${currentAvail / (1024 * 1024)} MB, needed=${needed / (1024 * 1024)} MB"
                    Log.e(TAG, msg)
                    return ModelResolution(
                        ready = false,
                        modelFile = model,
                        tokenizerFile = tokenizer,
                        statusMessage = msg,
                        availableBytes = currentAvail
                    )
                }

                if (stagedTok.length() != EXPECTED_TOKENIZER_SIZE_BYTES || stagedModel.length() != EXPECTED_MODEL_SIZE_BYTES) {
                    val msg = "Staged model/tokenizer size mismatch (model=${stagedModel.length()}, tok=${stagedTok.length()})"
                    Log.w(TAG, msg)
                    return ModelResolution(false, model, tokenizer, msg, currentAvail)
                }

                // Import tokenizer
                if (!tokenizer.exists()) {
                    val tmpTok = File(prodDir, "$TOKENIZER_FILENAME.tmp")
                    val (copiedBytes, hash) = streamCopyAndHash(stagedTok, tmpTok)
                    if (copiedBytes != EXPECTED_TOKENIZER_SIZE_BYTES || hash != EXPECTED_TOKENIZER_SHA256) {
                        tmpTok.delete()
                        return ModelResolution(false, model, tokenizer, "Staged tokenizer checksum failed: $hash", currentAvail)
                    }
                    if (!tmpTok.renameTo(tokenizer)) {
                        tmpTok.delete()
                        return ModelResolution(false, model, tokenizer, "Failed to finalize tokenizer file", currentAvail)
                    }
                }

                // Import model via 64 KB streaming buffer
                if (!model.exists()) {
                    val tmpMod = File(prodDir, "$MODEL_FILENAME.tmp")
                    val (copiedBytes, hash) = streamCopyAndHash(stagedModel, tmpMod)
                    if (copiedBytes != EXPECTED_MODEL_SIZE_BYTES || hash != EXPECTED_MODEL_SHA256) {
                        tmpMod.delete()
                        return ModelResolution(false, model, tokenizer, "Staged model checksum failed: $hash", currentAvail)
                    }
                    if (!tmpMod.renameTo(model)) {
                        tmpMod.delete()
                        return ModelResolution(false, model, tokenizer, "Failed to finalize model file", currentAvail)
                    }
                }

                writeVerificationReceipt(model, tokenizer)
                if (cleanStagedAfterImport) {
                    stagedModel.delete()
                    stagedTok.delete()
                }
                Log.i(TAG, "Successfully imported and verified production model into ${prodDir.absolutePath}")
                return ModelResolution(
                    ready = true,
                    modelFile = model,
                    tokenizerFile = tokenizer,
                    statusMessage = "Imported from app-specific staging and verified SHA-256",
                    availableBytes = availableStorageBytes(prodDir),
                    verifiedSha256 = EXPECTED_MODEL_SHA256
                )
            }
        }

        val missingMsg = "Offline model not provisioned in app storage (${prodDir.absolutePath}); deterministic fallback active."
        Log.i(TAG, missingMsg)
        return ModelResolution(
            ready = false,
            modelFile = model,
            tokenizerFile = tokenizer,
            statusMessage = missingMsg,
            availableBytes = avail
        )
    }

    private fun hasValidVerificationReceipt(model: File, tokenizer: File): Boolean {
        if (!metaFile.exists()) return false
        return try {
            val o = JSONObject(metaFile.readText(Charsets.UTF_8))
            o.optLong("model_size", -1L) == model.length() &&
                o.optLong("model_mtime", -1L) == model.lastModified() &&
                o.optString("model_sha256", "") == EXPECTED_MODEL_SHA256 &&
                o.optLong("tokenizer_size", -1L) == tokenizer.length() &&
                o.optLong("tokenizer_mtime", -1L) == tokenizer.lastModified() &&
                o.optString("tokenizer_sha256", "") == EXPECTED_TOKENIZER_SHA256
        } catch (e: Exception) {
            false
        }
    }

    private fun writeVerificationReceipt(model: File, tokenizer: File) {
        try {
            val o = JSONObject().apply {
                put("model_size", model.length())
                put("model_mtime", model.lastModified())
                put("model_sha256", EXPECTED_MODEL_SHA256)
                put("tokenizer_size", tokenizer.length())
                put("tokenizer_mtime", tokenizer.lastModified())
                put("tokenizer_sha256", EXPECTED_TOKENIZER_SHA256)
            }
            metaFile.writeText(o.toString(2), Charsets.UTF_8)
        } catch (e: Exception) {
            Log.w(TAG, "Could not write verification receipt: ${e.message}")
        }
    }
}

