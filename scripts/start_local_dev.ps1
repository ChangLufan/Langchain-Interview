$ErrorActionPreference = "Stop"
$ProjectRoot = "F:\PythonProject\easy-langent"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Script = Join-Path $ProjectRoot "scripts\local_dev_server.py"
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$cert = & $Python -c "import certifi; print(certifi.where())"

$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $Python
$psi.Arguments = "`"$Script`""
$psi.WorkingDirectory = $ProjectRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.EnvironmentVariables.Clear()
$psi.EnvironmentVariables["SystemRoot"] = $env:SystemRoot
$psi.EnvironmentVariables["COMSPEC"] = $env:COMSPEC
$psi.EnvironmentVariables["PATH"] = "$ProjectRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
$psi.EnvironmentVariables["SSL_CERT_FILE"] = $cert
$psi.EnvironmentVariables["PYTHONUTF8"] = "1"
$psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
if ($env:AI_BAILIAN_API_KEY) { $psi.EnvironmentVariables["AI_BAILIAN_API_KEY"] = $env:AI_BAILIAN_API_KEY }
if ($env:BASE_URL) { $psi.EnvironmentVariables["BASE_URL"] = $env:BASE_URL }
if ($env:MODEL_NAME) { $psi.EnvironmentVariables["MODEL_NAME"] = $env:MODEL_NAME }

$process = [System.Diagnostics.Process]::Start($psi)
$process.Id | Set-Content -Encoding UTF8 (Join-Path $LogDir "local_dev_server.pid")

Start-Sleep -Seconds 2
if ($process.HasExited) {
    throw "local dev server exited with code $($process.ExitCode)"
}

Write-Output "pid=$($process.Id)"
