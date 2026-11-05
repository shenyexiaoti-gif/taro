<#
X OAuth 1.0a の接続確認を一発で通すスクリプト（Windows用）

使い方（PowerShell で、このファイルのあるフォルダで）:
  powershell -ExecutionPolicy Bypass -File .\run_oauth1.ps1

やること:
  1. Python を探す（Microsoft Store の空箱 python.exe は避ける）
  2. .env が無い、または 1.0a の4つの値が無ければ、メモ帳で開いて止まる
  3. 静的チェック（取り違え・空白・全角の混入）。NG ならそこで止まる
  4. GET /2/users/me を1回だけ叩く。投稿はしない
  5. 画面の出力を oauth1_result.txt にも残す（秘密の値は伏字。そのまま貼ってよい）
#>

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'

function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Ng($m)   { Write-Host "  [NG]   $m" -ForegroundColor Red }
function Info($m) { Write-Host "         $m" -ForegroundColor Gray }
function Head($m) { Write-Host ""; Write-Host "== $m ==" -ForegroundColor Cyan }

Set-Location -Path $PSScriptRoot
$log = Join-Path $PSScriptRoot 'oauth1_result.txt'

function Show-EnvHelp {
    Info 'X_API_KEY / X_API_SECRET                  : Keys and tokens > Consumer Keys'
    Info 'X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET    : Keys and tokens > Authentication Tokens'
    Info '先に App permissions を Read and write にしてから Access Token を発行する'
}

# ---------------------------------------------------------------- 1. Python
Head '1. Python を探す'
$py = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $v = & py -3 --version 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -and $v -match 'Python 3') { $py = 'py'; $pyArgs = @('-3') }
}
if (-not $py) {
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($cmd.Source -like '*WindowsApps*') { continue }  # Store の空箱
        $v = & $name --version 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -and $v -match 'Python 3') { $py = $name; break }
    }
}
if (-not $py) {
    Ng 'Python 3 が見つからない。python.org から入れ、"Add python.exe to PATH" にチェックを入れる。'
    exit 1
}
$ver = (& $py @pyArgs --version 2>&1 | Out-String).Trim()
Ok "$py $($pyArgs -join ' ') ($ver)"

# ---------------------------------------------------------------- 2. .env
Head '2. .env を確認'
if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Ng '.env が無かったので .env.example から作った。メモ帳で開くので 1.0a の4つを埋めて保存し、もう一度実行する。'
    Show-EnvHelp
    Start-Process notepad.exe '.env'
    exit 1
}
Ok '.env あり'

# ---------------------------------------------------------------- 3. 静的チェック
Head '3. 静的チェック'
$check = & $py @pyArgs x_oauth1_check.py --check-config 2>&1 | Out-String
$checkRc = $LASTEXITCODE
Write-Host $check
if ($checkRc -ne 0) {
    if ($check -match '未設定') {
        Ng '.env に 1.0a の値が足りない。メモ帳で開くので追記して保存し、もう一度実行する。'
        Info '書き方は .env.example の「OAuth 1.0a」の節をそのまま写せばよい。'
        Show-EnvHelp
        Start-Process notepad.exe '.env'
    } else {
        Ng '静的チェックで NG。上の指摘を .env で直してから再実行する。'
    }
    exit 1
}
Ok '静的チェック通過'

# ---------------------------------------------------------------- 4. 実走
Head '4. users/me を1回叩く'
& $py @pyArgs x_oauth1_check.py 2>&1 | ForEach-Object -Begin {
    Set-Content -Path $log -Value "# X OAuth 1.0a 接続確認ログ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8
} -Process {
    $line = "$_"
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}
$rc = $LASTEXITCODE

# ---------------------------------------------------------------- 5. 結果
Head '5. 結果'
if ($rc -eq 0) {
    Ok 'OAuth 1.0a で X に接続できた'
    Info '投稿まで使うなら、上の「権限」が read-write か、Portal の表示で Read and write かを確認する。'
} else {
    Ng '接続できなかった。上の「判定」の順に疑う'
}
Info "出力は $log に保存した。秘密の値は伏字なので、そのまま貼ってよい。"
exit $rc
