# Research Copilot launcher.
#
# Starts everything the app needs, then opens it in the browser. Safe to run
# when parts are already up — each service is only started if its port is down,
# so double-clicking twice will not spawn duplicates.
#
# Ollama is required even on the hosted (Nemotron) engine: OpenRouter is a
# chat-completions gateway and does not serve the embedding model, so library
# search and chat-with-paper retrieval both embed through local Ollama.

$backendDir  = "D:\TEst\research-copilot\backend"
$frontendDir = "D:\TEst\research-copilot\frontend"

function Test-Port($port) {
    return [bool](Test-NetConnection -ComputerName "127.0.0.1" -Port $port `
        -WarningAction SilentlyContinue -InformationLevel Quiet)
}

function Wait-ForPort($port, $maxSeconds = 180) {
    $elapsed = 0
    while ($elapsed -lt $maxSeconds) {
        if (Test-Port $port) { return $true }
        Start-Sleep -Seconds 2
        $elapsed += 2
    }
    return $false
}

# --- Ollama (embeddings) -------------------------------------------------
if (-not (Test-Port 11434)) {
    $trayApp = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
    $cli     = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path $trayApp) {
        Start-Process -FilePath $trayApp
    } elseif (Test-Path $cli) {
        Start-Process -FilePath $cli -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden `
            -ErrorAction SilentlyContinue
    }
}

# --- Backend -------------------------------------------------------------
if (-not (Test-Port 8321)) {
    Start-Process -FilePath "cmd.exe" -ArgumentList @(
        '/k',
        "title Research Copilot - Backend && cd /d `"$backendDir`" && .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8321"
    )
}

# --- Frontend ------------------------------------------------------------
if (-not (Test-Port 3000)) {
    Start-Process -FilePath "cmd.exe" -ArgumentList @(
        '/k',
        "title Research Copilot - Frontend && cd /d `"$frontendDir`" && npm run dev"
    )
}

$ollamaUp   = Wait-ForPort 11434 60
$backendUp  = Wait-ForPort 8321
$frontendUp = Wait-ForPort 3000

if ($frontendUp) {
    Start-Process "http://localhost:3000"
}

# Only surface a dialog when something is actually wrong — a clean start stays
# silent so the launcher feels like opening an app, not running a script.
$problems = @()
if (-not $ollamaUp)   { $problems += "Ollama (port 11434) did not start. Library search and chat-with-paper will fail; other features still work." }
if (-not $backendUp)  { $problems += "Backend (port 8321) did not start. Check the 'Research Copilot - Backend' window." }
if (-not $frontendUp) { $problems += "Frontend (port 3000) did not start. Check the 'Research Copilot - Frontend' window." }

if ($problems.Count -gt 0) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        ($problems -join "`n`n"),
        "Research Copilot - startup problem",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Warning
    ) | Out-Null
}
