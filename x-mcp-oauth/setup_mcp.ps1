<#
X OAuth 1.0a MCP サーバーを Claude の設定に登録する（Windows用）

使い方（PowerShell で、このファイルのあるフォルダ x-mcp-oauth で）:
  powershell -ExecutionPolicy Bypass -File .\setup_mcp.ps1

先に Claude Code / Claude Desktop のアプリを完全に終了しておく。
起動中だと、アプリが終了時に設定を書き戻して、登録が消えることがある。

やること:
  1. Python を探す
  2. 鍵で X に繋がるか（--selftest）を1回見る
  3. 登録先の設定ファイルをバックアップし、mcpServers に "x-oauth1" を追記する
     既定は Claude Code（%USERPROFILE%\.claude.json）と Claude Desktop の両方
  4. 何を書いたかを表示する

秘密の値は設定ファイルに書かない。サーバーが同じフォルダの .env を絶対パスで読む。

  -Target Code     Claude Code だけに登録する
  -Target Desktop  Claude Desktop だけに登録する
  -Print           書き込まず、登録内容だけ表示する
#>
param(
    [ValidateSet('Both', 'Code', 'Desktop')]
    [string]$Target = 'Both',
    [switch]$Print
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'

function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Ng($m)   { Write-Host "  [NG]   $m" -ForegroundColor Red }
function Info($m) { Write-Host "         $m" -ForegroundColor Gray }
function Head($m) { Write-Host ""; Write-Host "== $m ==" -ForegroundColor Cyan }

Set-Location -Path $PSScriptRoot
$serverPath = Join-Path $PSScriptRoot 'x_mcp_server.py'
$envPath    = Join-Path $PSScriptRoot '.env'
$register   = Join-Path $PSScriptRoot 'mcp_register.py'

# ---------------------------------------------------------------- 1. Python
Head '1. Python を探す'
$py = $null; $pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $v = & py -3 --version 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -and $v -match 'Python 3') { $py = 'py'; $pyArgs = @('-3') }
}
if (-not $py) {
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($cmd.Source -like '*WindowsApps*') { continue }
        $v = & $name --version 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -and $v -match 'Python 3') { $py = $name; break }
    }
}
if (-not $py) { Ng 'Python 3 が見つからない。python.org から入れる。'; exit 1 }
# Claude から起動するときは py ランチャを通さず、python.exe の絶対パスで登録する
$pyExe = (& $py @pyArgs -c "import sys; print(sys.executable)" 2>&1 | Out-String).Trim()
if (-not (Test-Path $pyExe)) { Ng "python.exe の場所が取れなかった: $pyExe"; exit 1 }
Ok $pyExe

# ---------------------------------------------------------------- 2. 疎通
Head '2. 鍵で X に繋がるか確認'
if (-not (Test-Path $envPath)) {
    Ng '.env が無い。先に run_oauth1.ps1 で 1.0a を通しておく。'
    exit 1
}
$self = & $pyExe $serverPath --selftest 2>&1 | Out-String
Write-Host $self
if ($self -notmatch 'username') {
    Ng 'x_get_me が通らなかった。上の出力を確認する。登録は中止した。'
    exit 1
}
Ok 'サーバーが X に接続できることを確認'

# ---------------------------------------------------------------- 3. 登録
$targets = @()
if ($Target -in @('Both', 'Code'))    { $targets += @{ Name = 'Claude Code';    Path = (Join-Path $HOME '.claude.json'); Code = $true } }
if ($Target -in @('Both', 'Desktop')) { $targets += @{ Name = 'Claude Desktop'; Path = (Join-Path $env:APPDATA 'Claude\claude_desktop_config.json'); Code = $false } }

$failed = 0
foreach ($t in $targets) {
    Head "3. 登録: $($t.Name)"
    Info "対象: $($t.Path)"
    $regArgs = @($register, '--config', $t.Path, '--command', $pyExe,
                 '--arg', $serverPath, '--arg', '--env', '--arg', $envPath)
    if ($t.Code)  { $regArgs += '--code' }
    if ($Print)   { $regArgs += '--print' }
    & $pyExe @regArgs
    if ($LASTEXITCODE -ne 0) { $failed++; Ng "$($t.Name) への登録に失敗した" }
}

# ---------------------------------------------------------------- 4. 次にやること
Head '4. 次にやること'
if ($Print) { Info '-Print 指定のため、どこにも書き込んでいない。'; exit 0 }
Info 'Claude Code のアプリを開き直し、ローカルのセッション（このPCで動く方）を新しく始める。'
Info 'クラウドのセッションからは、このPCの MCP は見えない。'
Info 'ツール一覧に x-oauth1 が出れば成功。まず「x_get_me を呼んで」で疎通を見る。'
Info '元に戻すときは、表示されたバックアップを元のファイル名に戻す。'
exit $failed
