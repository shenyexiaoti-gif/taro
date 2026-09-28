<#
X OAuth 2.0 + PKCE を一発で通すための実走スクリプト（Windows用）

使い方（PowerShell で、このファイルのあるフォルダで）:
  powershell -ExecutionPolicy Bypass -File .\run_oauth2.ps1

やること:
  1. Python を探す（Microsoft Store の空箱 python.exe は避ける）
  2. .env が無ければ .env.example から作り、メモ帳で開いて止まる
  3. 静的チェック（--check-config）。NG ならそこで止まる
  4. 実走。認可URLをブラウザで開く → 承認 → トークン交換 → users/me → リフレッシュまで
  5. 画面の出力を oauth2_result.txt にも残す（トークンは伏字。そのまま貼ってよい）

-Manual を付けると、コールバックURLを手貼りする方式になる（redirect_uri が localhost 以外のとき）。
#>
param(
    [switch]$Manual,
    [int]$Timeout = 180
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'

function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Ng($m)   { Write-Host "  [NG]   $m" -ForegroundColor Red }
function Info($m) { Write-Host "         $m" -ForegroundColor Gray }
function Head($m) { Write-Host ""; Write-Host "== $m ==" -ForegroundColor Cyan }

Set-Location -Path $PSScriptRoot
$log = Join-Path $PSScriptRoot 'oauth2_result.txt'

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
    Ng '.env が無かったので .env.example から作った。メモ帳で開くので値を埋めて保存し、もう一度このスクリプトを実行する。'
    Info 'X_CLIENT_ID     : Developer Portal > Keys and tokens > OAuth 2.0 Client ID'
    Info 'X_CLIENT_SECRET : Type of App が Web App / Bot なら入れる。Native App なら空のまま'
    Info 'X_REDIRECT_URI  : Portal の Callback URI と1文字も違わず一致させる'
    Start-Process notepad.exe '.env'
    exit 1
}
Ok '.env あり'

# ---------------------------------------------------------------- 3. 静的チェック
Head '3. 静的チェック'
& $py @pyArgs x_oauth2_pkce_check.py --check-config
if ($LASTEXITCODE -ne 0) {
    Ng '静的チェックで NG。上の指摘を .env で直してから再実行する。'
    exit 1
}
Ok '静的チェック通過'

# ---------------------------------------------------------------- 4. 実走
Head '4. 実走（ブラウザで承認する）'
Info '認可URLが出たら自動でブラウザを開く。開かなければURLをコピーして貼る。'
Info '承認すると、このウィンドウに戻ってトークン交換 → users/me → リフレッシュまで進む。'

$flowArgs = @('x_oauth2_pkce_check.py', '--timeout', "$Timeout")
if ($Manual) { $flowArgs += '--manual' }

$opened = $false
& $py @pyArgs @flowArgs 2>&1 | ForEach-Object -Begin {
    Set-Content -Path $log -Value "# X OAuth 2.0 実走ログ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8
} -Process {
    $line = "$_"
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
    if (-not $opened -and $line -match '^https://[^\s]*oauth2/authorize\?') {
        $opened = $true
        Start-Process $line
    }
}
$rc = $LASTEXITCODE

# ---------------------------------------------------------------- 5. 結果
Head '5. 結果'
$text = Get-Content $log -Raw -Encoding UTF8
if ($rc -eq 0 -and $text -match 'リフレッシュ成功') {
    Ok 'OAuth 2.0 が最後まで通った（認可 → 交換 → users/me → リフレッシュ）'
} elseif ($rc -eq 0 -and $text -match 'トークン取得成功') {
    Ok 'トークン取得までは通った。リフレッシュ結果は上の出力を確認する'
} else {
    Ng 'どこかの工程で落ちた。README の「落ちたときの読み方」の表で当たりを付ける'
}
Info "出力は $log に保存した。トークンは伏字なので、そのまま貼ってよい。"
exit $rc
