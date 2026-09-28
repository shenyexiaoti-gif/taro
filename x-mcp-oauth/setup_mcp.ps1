<#
X OAuth 1.0a MCP サーバーを Claude の設定に登録する（Windows用）

使い方（PowerShell で、このファイルのあるフォルダ x-mcp-oauth で）:
  powershell -ExecutionPolicy Bypass -File .\setup_mcp.ps1

やること:
  1. Python を探す
  2. .env に 1.0a の4つが入っているか確認し、x_mcp_server.py の疎通（--selftest）を1回見る
  3. 登録先の設定ファイルを選ぶ（既定は Claude Desktop の claude_desktop_config.json）
  4. 設定ファイルをバックアップし、mcpServers に "x-oauth1" を追記する
  5. 何を書いたかを表示する

秘密の値は設定ファイルに書かない。サーバーが同じフォルダの .env から読む。
登録後、Claude を再起動すると x_get_me / x_search_recent / x_post_tweet が使える。

  -ConfigPath "パス"  登録先を明示する（Claude Code の .mcp.json など）
  -Print              書き込まず、追記する JSON だけ表示する
#>
param(
    [string]$ConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json",
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
# Claude が起動するときのため、絶対パスの python を控える
$pyExe = (Get-Command $py).Source
Ok "$pyExe"

# ---------------------------------------------------------------- 2. 疎通
Head '2. .env と疎通を確認'
if (-not (Test-Path '.env')) {
    Ng '.env が無い。先に run_oauth1.ps1 で 1.0a を通しておく。'
    exit 1
}
$self = & $py @pyArgs $serverPath --selftest 2>&1 | Out-String
Write-Host $self
if ($self -notmatch 'username') {
    Ng 'x_get_me が通らなかった。上の出力を確認する。設定登録は中止した。'
    exit 1
}
Ok 'サーバーが X に接続できることを確認'

# ---------------------------------------------------------------- 3. 追記する内容
Head '3. 登録内容'
# py ランチャは Claude の起動環境で解決できないことがあるので、python.exe の絶対パスで登録する
$launchExe = $pyExe
$launchArgs = @($serverPath)
if ($py -eq 'py') {
    # py ランチャしか無い場合は、それを使う（-3 を付ける）
    $launchExe = $pyExe
    $launchArgs = @('-3', $serverPath)
}
$entry = [ordered]@{
    command = $launchExe
    args    = $launchArgs
    cwd     = $PSScriptRoot
}
$snippet = @{ mcpServers = @{ 'x-oauth1' = $entry } } | ConvertTo-Json -Depth 6
Write-Host $snippet -ForegroundColor Gray

if ($Print) { Info '-Print 指定のため書き込まない。'; exit 0 }

# ---------------------------------------------------------------- 4. 設定ファイルへ書き込む
Head '4. 設定ファイルへ書き込む'
Info "対象: $ConfigPath"
$dir = Split-Path -Parent $ConfigPath
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

if (Test-Path $ConfigPath) {
    $backup = "$ConfigPath.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $ConfigPath $backup
    Ok "バックアップ: $backup"
    try {
        $conf = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Ng '既存の設定ファイルが JSON として読めない。手を加えず中止した。'
        Info '中身を確認するか、-Print で内容だけ受け取って手で貼る。'
        exit 1
    }
} else {
    $conf = [pscustomobject]@{}
    Info '設定ファイルが無いので新規に作る。'
}

# mcpServers が無ければ作る
if (-not ($conf.PSObject.Properties.Name -contains 'mcpServers')) {
    $conf | Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue ([pscustomobject]@{})
}
$existing = $conf.mcpServers.PSObject.Properties.Name -contains 'x-oauth1'
$entryObj = [pscustomobject]$entry
if ($existing) {
    $conf.mcpServers.'x-oauth1' = $entryObj
    Info '既存の x-oauth1 を上書きした。'
} else {
    $conf.mcpServers | Add-Member -NotePropertyName 'x-oauth1' -NotePropertyValue $entryObj
}

$conf | ConvertTo-Json -Depth 8 | Set-Content -Path $ConfigPath -Encoding UTF8
Ok '書き込み完了'

# ---------------------------------------------------------------- 5. 結果
Head '5. 次にやること'
Info 'Claude Desktop を完全に終了して、開き直す（タスクトレイからも終了）。'
Info '再起動後、ツール一覧に x_get_me / x_search_recent / x_post_tweet が出れば成功。'
Info 'まず x_get_me を呼んで自分のアカウントが返るか確認する。投稿は内容を承認してから。'
Info "登録先が違ったら、元に戻すにはバックアップを $ConfigPath に戻す。"
