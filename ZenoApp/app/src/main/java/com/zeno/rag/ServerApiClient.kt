package com.zeno.rag

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ServerApiClient(private var serverUrl: String, private var secretKey: String) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    fun updateCredentials(url: String, secret: String) {
        this.serverUrl = url.trimEnd('/')
        this.secretKey = secret
    }

    suspend fun getStatus(): Result<JSONObject> = withContext(Dispatchers.IO) {
        try {
            val url = "$serverUrl/api/status?secret=$secretKey"
            val request = Request.Builder()
                .url(url)
                .addHeader("X-Server-Secret", secretKey)
                .get()
                .build()

            val response = client.newCall(request).execute()
            val body = response.body?.string() ?: "{}"
            if (response.isSuccessful) {
                Result.success(JSONObject(body))
            } else {
                Result.failure(Exception("HTTP ${response.code}: $body"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getLogs(): Result<List<String>> = withContext(Dispatchers.IO) {
        try {
            val url = "$serverUrl/api/logs?secret=$secretKey"
            val request = Request.Builder()
                .url(url)
                .addHeader("X-Server-Secret", secretKey)
                .get()
                .build()

            val response = client.newCall(request).execute()
            val body = response.body?.string() ?: "{}"
            if (response.isSuccessful) {
                val json = JSONObject(body)
                val arr = json.optJSONArray("logs")
                val logsList = mutableListOf<String>()
                if (arr != null) {
                    for (i in 0 until arr.length()) {
                        logsList.add(arr.getString(i))
                    }
                }
                Result.success(logsList)
            } else {
                Result.failure(Exception("HTTP ${response.code}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun startJob(sourceUrl: String): Result<String> = withContext(Dispatchers.IO) {
        try {
            val url = "$serverUrl/api/start_job"
            val payload = JSONObject().put("source_url", sourceUrl).toString()
            val request = Request.Builder()
                .url(url)
                .addHeader("X-Server-Secret", secretKey)
                .post(payload.toRequestBody("application/json".toMediaType()))
                .build()

            val response = client.newCall(request).execute()
            val body = response.body?.string() ?: "{}"
            if (response.isSuccessful) {
                Result.success(body)
            } else {
                Result.failure(Exception("HTTP ${response.code}: $body"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun triggerUpload(targetUrl: String): Result<String> = withContext(Dispatchers.IO) {
        try {
            val url = "$serverUrl/api/trigger_upload"
            val payload = JSONObject().put("target_url", targetUrl).toString()
            val request = Request.Builder()
                .url(url)
                .addHeader("X-Server-Secret", secretKey)
                .post(payload.toRequestBody("application/json".toMediaType()))
                .build()

            val response = client.newCall(request).execute()
            val body = response.body?.string() ?: "{}"
            if (response.isSuccessful) {
                Result.success(body)
            } else {
                Result.failure(Exception("HTTP ${response.code}: $body"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
