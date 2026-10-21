<#
Installs the grandMA2 MCP server for Claude Code on Windows.

  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -GmaHost 192.168.0.50 -GmaPassword secret

What it does:
  1. installs the Python packages from requirements.txt (pip --user)
  2. registers the MCP server "grandma2" in Claude Code (user scope, all projects)
  3. installs the Claude skill "grandma2-lightshow" to ~/.claude/skills
  4. copies shows/claude_base.show.gz (empty show, Telnet enabled) into every grandMA2 onPC shows folder
#>
param(
    [string]$GmaHost = "",
    [int]$GmaPort = 0,
    [string]$GmaUser = "",
    [string]$GmaPassword = "",
    [switch]$SkipShow
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- Python -------------------------------------------------------------------
Step "Looking for Python 3.10+"
$python = $null
foreach ($cand in @(@("py", "-3"), @("python"), @("python3"))) {
    try {
        $exe = & $cand[0] $cand[1..9] -c "import sys; assert sys.version_info >= (3, 10); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $python = $exe.Trim(); break }
    } catch { }
}
if (-not $python) {
    throw "Python 3.10+ not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this script again."
}
Write-Host "Python: $python"

Step "Installing Python packages"
& $python -m pip install --user --upgrade --no-warn-script-location -r (Join-Path $repo "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
& $python -c "import mcp, librosa, soundfile, sounddevice; print('packages OK')"
if ($LASTEXITCODE -ne 0) { throw "Python packages could not be imported" }

# --- Claude Code --------------------------------------------------------------
Step "Registering MCP server 'grandma2' in Claude Code"
$claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
if (-not $claude) {
    $local = Join-Path $HOME ".local\bin\claude.exe"
    if (Test-Path $local) { $claude = $local }
}
$server = Join-Path $repo "server.py"
$envArgs = @()
if ($GmaHost)     { $envArgs += @("-e", "GMA2_HOST=$GmaHost") }
if ($GmaPort)     { $envArgs += @("-e", "GMA2_PORT=$GmaPort") }
if ($GmaUser)     { $envArgs += @("-e", "GMA2_USER=$GmaUser") }
if ($GmaPassword) { $envArgs += @("-e", "GMA2_PASSWORD=$GmaPassword") }
if ($claude) {
    # fails harmlessly when the server is not registered yet
    try { & $claude mcp remove grandma2 -s user 2>$null | Out-Null } catch { }
    & $claude mcp add --scope user grandma2 @envArgs -- $python $server
    if ($LASTEXITCODE -ne 0) { throw "claude mcp add failed" }
} else {
    Write-Warning "Claude Code CLI not found. Register the server manually:"
    Write-Host "  claude mcp add --scope user grandma2 $($envArgs -join ' ') -- `"$python`" `"$server`""
}

# --- Skill --------------------------------------------------------------------
Step "Installing skill 'grandma2-lightshow'"
$skillDst = Join-Path $HOME ".claude\skills\grandma2-lightshow"
New-Item -ItemType Directory -Force $skillDst | Out-Null
Copy-Item (Join-Path $repo "skills\grandma2-lightshow\*") $skillDst -Recurse -Force
Write-Host "Skill: $skillDst"

# --- Base show ----------------------------------------------------------------
if (-not $SkipShow) {
    Step "Copying base show (Telnet enabled) into grandMA2 onPC"
    $dataDirs = Get-ChildItem (Join-Path $env:ProgramData "MA Lighting Technologies\grandma") -Directory -Filter "gma2_V_*" -ErrorAction SilentlyContinue
    if (-not $dataDirs) {
        Write-Warning "grandMA2 onPC data folder not found (is onPC installed?). Skipping."
    }
    foreach ($d in $dataDirs) {
        $shows = Join-Path $d.FullName "shows"
        New-Item -ItemType Directory -Force $shows | Out-Null
        $dst = Join-Path $shows "claude_base.show.gz"
        if (Test-Path $dst) {
            Write-Host "Already there: $dst"
        } else {
            Copy-Item (Join-Path $repo "shows\claude_base.show.gz") $dst
            Write-Host "Copied to: $dst"
        }
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Start grandMA2 onPC and load the show 'claude_base' (Backup -> Load),"
Write-Host "     or enable Setup -> Console -> Global Settings -> Telnet: 'Login Enabled' in your own show."
Write-Host "  2. Start a NEW Claude Code session so the grandma2 tools are loaded."
Write-Host "  3. Ask Claude: 'Mach mir eine Lightshow zu C:\Musik\song.mp3'"
