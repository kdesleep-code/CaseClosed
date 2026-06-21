param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "0.0.0.0",
    [int]$FrontendPort = 8443,
    [switch]$NoHttps
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendRoot = Join-Path $Root "frontend"
$LogDir = Join-Path $Root ".tmp\dev-server-logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Get-PortProcessIds {
    param([int]$Port)

    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    $processIds = @($connections | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -and $_ -ne 0 })
    $netstatProcessIds = @(
        netstat -ano |
            Select-String -Pattern "LISTENING" |
            ForEach-Object {
                $parts = -split $_.Line.Trim()
                if ($parts.Count -ge 5 -and $parts[1] -match ":$Port$" -and $parts[3] -eq "LISTENING") {
                    [int]$parts[4]
                }
            }
    )
    @($processIds + $netstatProcessIds | Sort-Object -Unique)
}

function Stop-PortProcesses {
    param(
        [int]$Port,
        [string]$Name
    )

    $processIds = Get-PortProcessIds -Port $Port
    if ($processIds.Count -eq 0) {
        Write-Host "${Name}: no process is listening on port $Port."
        return
    }

    Write-Host "${Name}: stopping old process(es) on port ${Port}: $($processIds -join ', ')"
    foreach ($processId in $processIds) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            Stop-Process -Id $processId -Force
        }
    }

    $deadline = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 250
        $remaining = Get-PortProcessIds -Port $Port
    } while ($remaining.Count -gt 0 -and (Get-Date) -lt $deadline)

    if ($remaining.Count -gt 0) {
        throw "${Name}: failed to clear port $Port. Remaining process(es): $($remaining -join ', ')"
    }

    Write-Host "${Name}: confirmed no old process remains on port $Port."
}

function Stop-PortRangeProcesses {
    param(
        [int[]]$Ports,
        [string]$Name
    )

    foreach ($port in ($Ports | Sort-Object -Unique)) {
        Stop-PortProcesses -Port $port -Name $Name
    }
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [string]$Name,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            if ($Url.StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
                $statusCode = & curl.exe -k -s -o NUL -w "%{http_code}" $Url
                if ($LASTEXITCODE -eq 0 -and [int]$statusCode -ge 200 -and [int]$statusCode -lt 500) {
                    Write-Host "${Name}: ready ($statusCode) $Url"
                    return
                }
            } else {
                $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                    Write-Host "${Name}: ready ($($response.StatusCode)) $Url"
                    return
                }
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    throw "${Name}: did not become ready within $TimeoutSeconds seconds: $Url"
}

function Wait-PortOpen {
    param(
        [string]$HostName,
        [int]$Port,
        [string]$Name,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $tcpClient = New-Object System.Net.Sockets.TcpClient
            $connect = $tcpClient.BeginConnect($HostName, $Port, $null, $null)
            if ($connect.AsyncWaitHandle.WaitOne(1000, $false)) {
                $tcpClient.EndConnect($connect)
                $tcpClient.Close()
                Write-Host "${Name}: ready (tcp) ${HostName}:${Port}"
                return
            }
            $tcpClient.Close()
        } catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $deadline)

    throw "${Name}: port did not open within $TimeoutSeconds seconds: ${HostName}:${Port}"
}

Set-Location $Root

Stop-PortProcesses -Port $BackendPort -Name "Backend"
$frontendPortsToClear = @($FrontendPort..($FrontendPort + 10)) + @(5173)
Stop-PortRangeProcesses -Ports $frontendPortsToClear -Name "Frontend"

$backendOut = Join-Path $LogDir "backend.out.log"
$backendErr = Join-Path $LogDir "backend.err.log"
$frontendOut = Join-Path $LogDir "frontend.out.log"
$frontendErr = Join-Path $LogDir "frontend.err.log"

Remove-Item -LiteralPath $backendOut, $backendErr, $frontendOut, $frontendErr -ErrorAction SilentlyContinue

$backendArgs = @(
    "-m", "uvicorn",
    "caseclosed.main:app",
    "--app-dir", "backend/src",
    "--env-file", ".env",
    "--host", $BackendHost,
    "--port", [string]$BackendPort
)

$vitePath = Join-Path $FrontendRoot "node_modules\vite\bin\vite.js"
$frontendCommand = "Set-Location -LiteralPath `"$FrontendRoot`"; node `"$vitePath`" --host $FrontendHost --port $FrontendPort --strictPort"
if ($NoHttps) {
    $frontendCommand += " --https=false"
}
$frontendEncodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($frontendCommand))

Write-Host "Backend: starting python $($backendArgs -join ' ')"
$backendProcess = Start-Process `
    -FilePath "python" `
    -ArgumentList $backendArgs `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru

Write-Host "Frontend: starting powershell.exe -NoExit -EncodedCommand <frontend dev server>"
$frontendProcess = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-EncodedCommand", $frontendEncodedCommand) `
    -WorkingDirectory $FrontendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $frontendOut `
    -RedirectStandardError $frontendErr `
    -PassThru

Wait-HttpOk -Url "http://127.0.0.1:$BackendPort/health" -Name "Backend"

$frontendScheme = if ($NoHttps) { "http" } elseif (Test-Path -LiteralPath (Join-Path $Root "certs\caseclosed-dev.pfx")) { "https" } else { "http" }
$frontendUrl = "${frontendScheme}://127.0.0.1:${FrontendPort}/"
if ($frontendScheme -eq "https") {
    Wait-PortOpen -HostName "127.0.0.1" -Port $FrontendPort -Name "Frontend"
} else {
    Wait-HttpOk -Url $frontendUrl -Name "Frontend"
}

Write-Host ""
Write-Host "CaseClosed dev servers restarted."
Write-Host "Backend PID : $($backendProcess.Id)"
Write-Host "Frontend PID: $($frontendProcess.Id)"
Write-Host "Backend URL : http://127.0.0.1:$BackendPort"
Write-Host "Frontend URL: $frontendUrl"
Write-Host "Logs        : $LogDir"
