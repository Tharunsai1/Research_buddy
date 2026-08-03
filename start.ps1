# Research Copilot launcher.
#
# Starts everything the app needs, then opens it in the browser. Safe to run
# when parts are already up — each service is only started if its port is down,
# so double-clicking twice will not spawn duplicates.
#
# Ollama is required even on the hosted (Nemotron) engine: OpenRouter is a
# chat-completions gateway and does not serve the embedding model, so library
# search and chat-with-paper retrieval both embed through local Ollama.

$backendDir  = Join-Path $PSScriptRoot "backend"
$frontendDir = Join-Path $PSScriptRoot "frontend"

# Launched from the desktop shortcut there is no console to print to, so an
# unset-up checkout would fail invisibly. Check first and say what to run.
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$setup = @()
if (-not (Test-Path $venvPython)) {
    $setup += "Backend dependencies are missing. In the repo folder run:`n" +
              "    cd backend`n" +
              "    python -m venv .venv`n" +
              "    .venv\Scripts\pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    $setup += "Frontend dependencies are missing. In the repo folder run:`n" +
              "    cd frontend`n" +
              "    npm install"
}

# Locate Node rather than trusting PATH. A launcher started from a process
# that predates the Node install hands that stale environment to everything it
# spawns; the frontend console then dies on its own and the app just never
# comes up. Finding npm.cmd is not enough on its own — npm shells out to
# `next`, which looks up `node` on PATH — so the directory is put on the
# child's PATH below, not merely used to call npm.
$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npmCmd) {
    foreach ($candidate in @("$env:ProgramFiles\nodejs\npm.cmd",
                             "${env:ProgramFiles(x86)}\nodejs\npm.cmd",
                             "$env:LOCALAPPDATA\Programs\nodejs\npm.cmd")) {
        if (Test-Path $candidate) { $npmCmd = $candidate; break }
    }
}
if (-not $npmCmd) {
    $setup += "Node.js was not found. Install it from https://nodejs.org (LTS), " +
              "then run 'npm install' in the frontend folder."
} else {
    $nodeDir = Split-Path $npmCmd -Parent
}
if ($setup.Count -gt 0) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        ($setup -join "`n`n"),
        "Research Copilot - setup incomplete",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}

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
        "title Research Copilot - Frontend && cd /d `"$frontendDir`" && set `"PATH=$nodeDir;%PATH%`" && `"$npmCmd`" run dev"
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
