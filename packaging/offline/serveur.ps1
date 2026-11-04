# Serveur web minimal du registre hors ligne, pour Windows : rien à installer
# (PowerShell et .NET sont fournis avec Windows). Écoute sur cet ordinateur seulement.
# Usage : powershell -ExecutionPolicy Bypass -File serveur.ps1 -Root <dossier site>
param([Parameter(Mandatory = $true)][string]$Root)
$ErrorActionPreference = 'Stop'

$types = @{
    '.html' = 'text/html; charset=utf-8'; '.js' = 'text/javascript; charset=utf-8'
    '.css' = 'text/css; charset=utf-8'; '.json' = 'application/json'
    '.md' = 'text/plain; charset=utf-8'; '.txt' = 'text/plain; charset=utf-8'
    '.woff2' = 'font/woff2'; '.png' = 'image/png'; '.jpg' = 'image/jpeg'
    '.jpeg' = 'image/jpeg'; '.svg' = 'image/svg+xml'; '.ico' = 'image/x-icon'
}
$rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
if (-not (Test-Path -LiteralPath (Join-Path $rootFull 'index.html'))) {
    Write-Host "Dossier « site » introuvable : décompressez toute l'archive avant de lancer."
    Read-Host 'Entrée pour fermer'
    exit 1
}

$listener = $null
foreach ($port in 8000..8019) {
    $candidate = New-Object System.Net.HttpListener
    $candidate.Prefixes.Add("http://localhost:$port/")
    try { $candidate.Start(); $listener = $candidate; break }
    catch { $candidate.Close() }
}
if ($null -eq $listener) {
    Write-Host 'Aucun port libre entre 8000 et 8019.'
    Read-Host 'Entrée pour fermer'
    exit 1
}

$url = "http://localhost:$port/"
Write-Host 'Registre IA 2027 — hors ligne'
Write-Host "Adresse : $url"
Write-Host 'Laissez cette fenêtre ouverte pendant la consultation ; fermez-la pour arrêter.'
Start-Process $url

function Send-Response($context, [int]$status, [byte[]]$bytes, [string]$type) {
    $response = $context.Response
    $response.StatusCode = $status
    $response.ContentType = $type
    $response.Headers['Cache-Control'] = 'no-cache'
    $response.ContentLength64 = $bytes.Length
    if ($context.Request.HttpMethod -ne 'HEAD') { $response.OutputStream.Write($bytes, 0, $bytes.Length) }
    $response.Close()
}

$notFound = [System.Text.Encoding]::UTF8.GetBytes('Not found')
try {
    while ($listener.IsListening) {
        # Short waits keep Ctrl+C responsive while idle.
        $pending = $listener.GetContextAsync()
        while (-not $pending.AsyncWaitHandle.WaitOne(500)) { }
        $context = $pending.GetAwaiter().GetResult()
        try {
            $method = $context.Request.HttpMethod
            if ($method -ne 'GET' -and $method -ne 'HEAD') {
                Send-Response $context 405 ([System.Text.Encoding]::UTF8.GetBytes('Method not allowed')) 'text/plain'
                continue
            }
            $path = [System.Uri]::UnescapeDataString($context.Request.Url.AbsolutePath)
            if ($path.EndsWith('/')) { $path += 'index.html' }
            $file = [System.IO.Path]::GetFullPath((Join-Path $rootFull ($path.TrimStart('/') -replace '/', '\')))
            if ($file.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -and
                (Test-Path -LiteralPath $file -PathType Leaf)) {
                $extension = [System.IO.Path]::GetExtension($file).ToLowerInvariant()
                $type = if ($types.ContainsKey($extension)) { $types[$extension] } else { 'application/octet-stream' }
                Send-Response $context 200 ([System.IO.File]::ReadAllBytes($file)) $type
            } else {
                Send-Response $context 404 $notFound 'text/plain'
            }
        } catch {
            # The browser closed the connection mid-answer: nothing to do, keep serving.
            try { $context.Response.Abort() } catch { }
        }
    }
} finally {
    $listener.Stop()
    $listener.Close()
}
