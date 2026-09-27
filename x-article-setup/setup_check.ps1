<#
X記事ワークフロー 導入診断スクリプト（Windows用）

使い方（PowerShell を開いて、このファイルのあるフォルダで）:
  診断だけ    : powershell -ExecutionPolicy Bypass -File .\setup_check.ps1
  直せる所は直す: powershell -ExecutionPolicy Bypass -File .\setup_check.ps1 -Fix
  作業フォルダが別の場所なら -Workspace "C:\Users\<名前>\claude-code" を足す

-ExecutionPolicy Bypass を付けるのは、実行制限が掛かったままでもこのスクリプトだけは動かすため。
-Fix を付けない限り、何も書き換えない。
X API は叩かない（読む系は課金されて 402 の原因になるため）。
#>
param(
    [string]$Workspace = (Join-Path $HOME 'claude-code'),
    [switch]$Fix
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$script:ng = 0
$script:warn = 0
function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Ng($m)   { $script:ng++;   Write-Host "  [NG]   $m" -ForegroundColor Red }
function Warn($m) { $script:warn++; Write-Host "  [注意] $m" -ForegroundColor Yellow }
function Info($m) { Write-Host "         $m" -ForegroundColor Gray }
function Head($m) { Write-Host ""; Write-Host "== $m ==" -ForegroundColor Cyan }

function Refresh-Path {
    # VS Code を開き直さなくても、この窓の中だけは最新の PATH で確認できるようにする
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($m, $u) | Where-Object { $_ }) -join ';'
}

function Run-Quiet([string]$exe, [string[]]$argv) {
    try {
        $out = & $exe @argv 2>&1 | Out-String
        return @{ Code = $LASTEXITCODE; Out = $out.Trim() }
    } catch {
        return @{ Code = -1; Out = $_.Exception.Message }
    }
}

Write-Host "X記事ワークフロー 導入診断" -ForegroundColor Cyan
if ($Fix) { Write-Host "モード: -Fix（直せる所は直す）" } else { Write-Host "モード: 診断のみ（-Fix を付けると直せる所は直す）" }
Refresh-Path

# ---------------------------------------------------------------
Head "1. PowerShell の実行制限（STEP 0.5-①）"
$pol = Get-ExecutionPolicy -Scope CurrentUser
if ($pol -in @('RemoteSigned', 'Unrestricted', 'Bypass')) {
    Ok "CurrentUser = $pol"
} elseif ($Fix) {
    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
    Ok "CurrentUser を RemoteSigned に変更した（元は $pol）"
} else {
    Ng "CurrentUser = $pol のまま。スクリプトが「実行が無効」で弾かれる"
    Info "-Fix で直す。手でやるなら: Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned"
}

# ---------------------------------------------------------------
Head "2. 文字化け対策 PYTHONUTF8（STEP 0.5-②）"
$u8 = [Environment]::GetEnvironmentVariable('PYTHONUTF8', 'User')
if ($u8 -eq '1') {
    Ok "PYTHONUTF8 = 1"
} elseif ($Fix) {
    [Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'User')
    $env:PYTHONUTF8 = '1'
    Ok "PYTHONUTF8 = 1 を設定した（VS Code は開き直すまで古いまま）"
} else {
    Ng "PYTHONUTF8 が未設定。日本語が化ける"
    Info "-Fix で直す"
}

# ---------------------------------------------------------------
Head "3. Python（STEP 0.5-③）"
$pyCmds = @(Get-Command python -All -ErrorAction SilentlyContinue)
if ($pyCmds.Count -eq 0) {
    Ng "python が見つからない"
    Info "python.org/downloads → standalone installer → 最初の画面で「Add python.exe to PATH」に必ずチェック"
} else {
    $first = $pyCmds[0].Source
    if ($first -like '*\WindowsApps\*') {
        Ng "python が中身のない空箱を指している: $first"
        Info "本物を入れる: python.org/downloads → standalone installer → 「Add python.exe to PATH」にチェック"
        Info "入れた後も直らなければ: 設定 → アプリ → アプリ実行エイリアス → python.exe と python3.exe をオフ"
    } else {
        $r = Run-Quiet 'python' @('--version')
        if ($r.Out -match 'Python (\d+)\.(\d+)') {
            $maj = [int]$Matches[1]; $min = [int]$Matches[2]
            if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 10)) {
                Ok "$($r.Out)  ($first)"
            } else {
                Ng "$($r.Out) は古い。3.10 以上が必要"
            }
            $pil = Run-Quiet 'python' @('-c', 'import PIL, numpy')
            if ($pil.Code -eq 0) { Ok "Pillow / numpy あり（サムネ生成用）" }
            else { Warn "Pillow / numpy が無い。サムネ生成を使うなら: pip install Pillow numpy" }
        } else {
            Ng "python --version で数字が出ない: '$($r.Out)'"
        }
    }
}

# ---------------------------------------------------------------
Head "4. Node.js（STEP 0.5-④）"
$r = Run-Quiet 'node' @('--version')
if ($r.Out -match '^v\d+') {
    Ok "node $($r.Out)"
    $hasNode = $true
} else {
    Ng "node が動かない。nodejs.org から LTS 版を入れる（Tools for Native Modules のチェックは外す）"
    $hasNode = $false
}

# ---------------------------------------------------------------
Head "5. xurl 本体（STEP 6-0 の無言症状）"
$xurlExe = $null
if ($hasNode) {
    $npmRoot = (Run-Quiet 'npm' @('root', '-g')).Out
    $pkg = Join-Path $npmRoot '@xdevplatform\xurl'
    if (-not (Test-Path $pkg)) {
        if ($Fix) {
            Info "npm install -g @xdevplatform/xurl を実行する"
            & npm install -g '@xdevplatform/xurl'
        } else {
            Ng "xurl のパッケージが入っていない: $pkg"
            Info "-Fix で npm install -g @xdevplatform/xurl まで実行する"
        }
    }
    if (Test-Path $pkg) {
        $found = Get-ChildItem -Path $pkg -Recurse -Filter 'xurl.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $found -and $Fix -and (Test-Path (Join-Path $pkg 'install.js'))) {
            Info "本体が無いので node install.js で取りに行く"
            Push-Location $pkg
            & node install.js
            Pop-Location
            $found = Get-ChildItem -Path $pkg -Recurse -Filter 'xurl.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if ($found) {
            $xurlExe = $found.FullName
            Ok "xurl.exe あり: $xurlExe"
            $binDir = $found.DirectoryName
            $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
            $inPath = ($userPath -split ';') | Where-Object { $_.TrimEnd('\') -ieq $binDir.TrimEnd('\') }
            if ($inPath) {
                Ok "xurl.exe のフォルダはユーザー PATH に入っている"
            } elseif ($Fix) {
                $newPath = (@($userPath, $binDir) | Where-Object { $_ }) -join ';'
                [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
                Refresh-Path
                Ok "ユーザー PATH に追加した: $binDir"
            } else {
                Ng "xurl.exe のフォルダが PATH に無い: $binDir"
                Info "-Fix で追加する"
            }
            $h = Run-Quiet $xurlExe @('--help')
            if ($h.Out.Length -gt 50) { Ok "xurl --help が説明を返した" }
            else { Ng "xurl --help が何も返さない。本体が壊れている可能性。-Fix で取り直す前に $pkg を消してから再実行" }
        } else {
            Ng "xurl.exe が無い（npm がインストールスクリプトを止めた状態）"
            Info "-Fix で node install.js を実行して本体を取る"
        }
    }
}

# ---------------------------------------------------------------
Head "6. 作業フォルダ: $Workspace"
if (-not (Test-Path $Workspace)) {
    Ng "作業フォルダが無い。別の場所なら -Workspace でパスを渡す"
} else {
    if ($Workspace -match 'OneDrive|個人用') {
        Warn "クラウド同期フォルダの中にある。ユーザー直下（%USERPROFILE%）に移すのが安全"
    }
    $need = @(
        'CLAUDE.md',
        'skills\x_article_workflow\SKILL.md',
        'skills\x_article_workflow\post_article.py',
        'skills\buzz_style\SKILL.md',
        'skills\buzz_voice\SKILL.md',
        'skills\buzz_blueprint\SKILL.md',
        'skills\hook_words\SKILL.md',
        'materials\master_databank.md',
        'materials\past_articles_index.md',
        'materials\reference_articles.md',
        'outputs\x_articles'
    )
    foreach ($n in $need) {
        if (Test-Path (Join-Path $Workspace $n)) { Ok $n } else { Ng "$n が無い" }
    }
    # 最新版 ZIP（2026-08-28 以降）で入るもの。無ければ旧版のまま
    $newer = @(
        'skills\japanese_style\SKILL.md',
        'skills\x_article_workflow\reader_inspection.md',
        'projects\article_thumbnails\make.py'
    )
    foreach ($n in $newer) {
        if (-not (Test-Path (Join-Path $Workspace $n))) { Warn "$n が無い（最新版 ZIP 待ち）" }
    }
    $neta = @(Get-ChildItem -Path (Join-Path $Workspace 'skills\x_article_workflow\knowledge') -Filter 'ネタ帳_*.md' -ErrorAction SilentlyContinue)
    if ($neta.Count -gt 0) { Ok "ネタ帳: $($neta[0].Name)" } else { Warn "knowledge\ネタ帳_<名前>.md が無い" }

    # post_article.py の xurl 呼び出し
    $pa = Join-Path $Workspace 'skills\x_article_workflow\post_article.py'
    if (Test-Path $pa) {
        $src = Get-Content $pa -Raw -Encoding UTF8
        if ($src -match 'xurl\.exe') {
            Ok "post_article.py は xurl.exe を直接呼んでいる"
        } elseif ($src -match 'npx') {
            Warn "post_article.py はまだ npx 経由。無言症状が出るなら xurl.exe の絶対パスに差し替える"
            if ($xurlExe) { Info "差し替え先: $xurlExe" }
        }
        # 貼り付け文で直すと「--post で --user 無しなら exit(8)」になる。argparse の required=True でも可
        if (($src -match "add_argument\(\s*['""]--user['""][^)]*required\s*=\s*True") -or ($src -match 'exit\(\s*8\s*\)')) {
            Ok "--user は必須になっている"
        } else {
            Warn "--user が省略できる。別の垢に入る事故の元（README の貼り付け文で必須化する）"
        }
    }

    # フック
    $set = Join-Path $Workspace '.claude\settings.local.json'
    if (Test-Path $set) {
        $s = Get-Content $set -Raw -Encoding UTF8
        if ($s -match 'check_hook\.py') { Ok "check_hook.py がフック登録済み" }
        elseif ($s -match 'check_hook\.sh') { Warn "check_hook.sh（bash 版）が登録されている。Windows では check_hook.py に差し替える" }
        else { Warn "check_hook のフック登録が無い" }
    } else {
        Warn ".claude\settings.local.json が無い（フック未登録）"
    }
    if (Test-Path (Join-Path $Workspace 'skills\x_article_workflow\check_hook.py')) { Ok "check_hook.py あり" }
    else { Warn "skills\x_article_workflow\check_hook.py が無い" }

    # OpenAI キー（中身は表示しない）
    $envFile = Join-Path $Workspace 'projects\.env'
    if ((Test-Path $envFile) -and ((Get-Content $envFile -Encoding UTF8) -match '^\s*OPENAI_API_KEY\s*=\s*\S+')) {
        Ok "projects\.env に OPENAI_API_KEY あり"
    } else {
        Warn "OPENAI_API_KEY が無い。サムネ無しで投入される"
    }
}

# ---------------------------------------------------------------
Head "結果"
if ($script:ng -eq 0) {
    Write-Host "  NG 0件 / 注意 $($script:warn)件" -ForegroundColor Green
} else {
    Write-Host "  NG $($script:ng)件 / 注意 $($script:warn)件" -ForegroundColor Red
    if (-not $Fix) { Write-Host "  -Fix を付けて再実行すると、実行制限・PYTHONUTF8・xurl・PATH は自動で直す" }
}
Write-Host "  PATH や環境変数を変えたときは、最後に VS Code を閉じて開き直すこと（開き直すまで VS Code 側は古いまま）"
Write-Host "  X の残高（402）と認証は、ここでは確認しない。developer.x.com のダッシュボードで見る"
