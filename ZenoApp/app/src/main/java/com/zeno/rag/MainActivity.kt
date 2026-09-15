package com.zeno.rag

import android.content.Context
import android.content.SharedPreferences
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.zeno.rag.databinding.ActivityMainBinding
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var apiClient: ServerApiClient
    private lateinit var notificationHelper: NotificationHelper
    private lateinit var prefs: SharedPreferences

    private var pollingJob: Job? = null
    private var lastState: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        notificationHelper = NotificationHelper(this)
        prefs = getSharedPreferences("zeno_prefs", Context.MODE_PRIVATE)

        val savedUrl = prefs.getString("server_url", "http://10.0.2.2:8000") ?: "http://10.0.2.2:8000"
        val savedSecret = prefs.getString("secret_key", "zeno_secret_12345") ?: "zeno_secret_12345"

        binding.etServerUrl.setText(savedUrl)
        binding.etSecretKey.setText(savedSecret)

        apiClient = ServerApiClient(savedUrl, savedSecret)

        binding.btnConnect.setOnClickListener {
            val url = binding.etServerUrl.text.toString().trim()
            val secret = binding.etSecretKey.text.toString().trim()

            if (url.isEmpty() || secret.isEmpty()) {
                Toast.makeText(this, "Please enter Server URL and Secret Key", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            prefs.edit()
                .putString("server_url", url)
                .putString("secret_key", secret)
                .apply()

            apiClient.updateCredentials(url, secret)
            Toast.makeText(this, "Credentials saved. Connecting...", Toast.LENGTH_SHORT).show()
            startPolling()
        }

        binding.btnStartDownload.setOnClickListener {
            val sourceLink = binding.etSourceLink.text.toString().trim()
            if (sourceLink.isEmpty()) {
                Toast.makeText(this, "Enter source download link first!", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            lifecycleScope.launch {
                binding.btnStartDownload.isEnabled = false
                val result = apiClient.startJob(sourceLink)
                result.onSuccess {
                    Toast.makeText(this@MainActivity, "Download & Process Job Started!", Toast.LENGTH_LONG).show()
                }.onFailure { err ->
                    Toast.makeText(this@MainActivity, "Failed: ${err.message}", Toast.LENGTH_LONG).show()
                }
                binding.btnStartDownload.isEnabled = true
                fetchStatusAndLogs()
            }
        }

        binding.btnTriggerUpload.setOnClickListener {
            val targetLink = binding.etTargetLink.text.toString().trim()
            if (targetLink.isEmpty()) {
                Toast.makeText(this, "Enter target upload link first!", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            lifecycleScope.launch {
                binding.btnTriggerUpload.isEnabled = false
                val result = apiClient.triggerUpload(targetLink)
                result.onSuccess {
                    Toast.makeText(this@MainActivity, "Upload Triggered Successfully!", Toast.LENGTH_LONG).show()
                }.onFailure { err ->
                    Toast.makeText(this@MainActivity, "Failed: ${err.message}", Toast.LENGTH_LONG).show()
                }
                binding.btnTriggerUpload.isEnabled = true
                fetchStatusAndLogs()
            }
        }

        binding.btnRefresh.setOnClickListener {
            fetchStatusAndLogs()
        }

        startPolling()
    }

    private fun startPolling() {
        pollingJob?.cancel()
        pollingJob = lifecycleScope.launch {
            while (isActive) {
                fetchStatusAndLogs()
                delay(3000)
            }
        }
    }

    private fun fetchStatusAndLogs() {
        lifecycleScope.launch {
            val statusResult = apiClient.getStatus()
            statusResult.onSuccess { json ->
                binding.tvStatusBadge.text = "CONNECTED"
                binding.tvStatusBadge.setBackgroundColor(Color.parseColor("#4CAF50"))

                val state = json.optString("state", "IDLE")
                val totalBooks = json.optInt("total_books", 0)
                val completedBooks = json.optInt("completed_books", 0)
                val progressPct = json.optDouble("progress_percent", 0.0)
                val faissCount = json.optInt("faiss_count", 0)
                val lastError = json.optString("last_error", "")

                binding.tvJobState.text = "State: $state"
                binding.progressBar.progress = progressPct.toInt()
                binding.tvBooksCount.text = "Books: $completedBooks / $totalBooks (${progressPct.toInt()}%)"
                binding.tvFaissCount.text = "FAISS: $faissCount"

                // Check state transitions for notifications
                if (state != lastState) {
                    if (state == "ERROR") {
                        binding.errorBanner.visibility = View.VISIBLE
                        binding.tvErrorMessage.text = lastError.ifEmpty { "An unexpected error occurred on Zeno Server." }
                        notificationHelper.sendErrorNotification("Zeno Server Error", lastError.ifEmpty { "Processing encountered an error." })
                    } else if (state == "COMPLETED" || state == "WAITING_FOR_UPLOAD") {
                        binding.errorBanner.visibility = View.GONE
                        notificationHelper.sendSuccessNotification("Zeno Task Completed!", "All $completedBooks books processed successfully!")
                    } else {
                        binding.errorBanner.visibility = View.GONE
                    }
                    lastState = state
                }
            }.onFailure { err ->
                binding.tvStatusBadge.text = "OFFLINE"
                binding.tvStatusBadge.setBackgroundColor(Color.parseColor("#FF5252"))
                binding.tvJobState.text = "State: UNREACHABLE"
            }

            val logsResult = apiClient.getLogs()
            logsResult.onSuccess { logs ->
                if (logs.isNotEmpty()) {
                    binding.tvLogsTerminal.text = logs.joinToString("\n")
                    binding.scrollTerminal.post {
                        binding.scrollTerminal.fullScroll(View.FOCUS_DOWN)
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        pollingJob?.cancel()
    }
}
