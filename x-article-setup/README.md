# X記事ワークフロー 導入の詰まり対策セット（Windows用）

導入手順書で実際に止まった所を、ファイルで潰すためのセット。
手元の claude-code フォルダに持っていって使う。

| ファイル | 潰すもの | 置き場所 |
|---|---|---|
| setup_check.ps1 | STEP 0.5の飛ばし／実行制限／Pythonの空箱／xurlの無言／npx問題／PATHの反映 | どこでもよい（例：claude-code\） |
| check_hook.py | check_hook.sh が Windows で動かない | claude-code\skills\x_article_workflow\ |
| settings.local.json.example | フック登録 | 中身を claude-code\.claude\settings.local.json へ |
| CLAUDE_md_追記.md | ネタ出しの主軸ズレ／会話切れで消える | 中身を claude-code\CLAUDE.md の末尾へ |
| user必須化_貼り付け文.md | --user 省略で別垢に入る | 手元の Claude Code に貼る |

## 1. 診断スクリプト setup_check.ps1

VS Code のターミナル（PowerShell）で、ファイルを置いたフォルダに移動して打つ。

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_check.ps1
```

赤の [NG] と黄の [注意] だけ見ればよい。直せる所をまとめて直すなら -Fix を付ける。

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_check.ps1 -Fix
```

-Fix が自動でやること
- 実行制限を RemoteSigned にする（STEP 0.5-①）
- PYTHONUTF8=1 を設定する（STEP 0.5-②）
- xurl が無ければ npm install -g、本体 xurl.exe が無ければ node install.js で取る（6-0）
- xurl.exe のフォルダをユーザー PATH に足す（6-0）

-Fix でもやらないこと（表示だけ）
- Python と Node のインストール。空箱を検出したら、入れ直し方を表示する
- post_article.py の書き換え。xurl.exe の絶対パスを表示するので、差し替えは手元の Claude Code に頼む
- X API を叩く確認。読む系は課金されて 402 の原因になるので、残高と認証は developer.x.com で見る

作業フォルダが C:\Users\<名前>\claude-code 以外なら、-Workspace "<パス>" を足す。
最後に VS Code を閉じて開き直す。スクリプトの窓の中では PATH を読み直しているが、VS Code 本体は開き直すまで古いまま。

## 2. フック check_hook.py

check_hook.sh と同じ動きを Python だけで書いたもの。jq も bash も要らない。

1. check_hook.py を claude-code\skills\x_article_workflow\ に置く（post_article.py と同じフォルダ）
2. settings.local.json.example の中身を claude-code\.claude\settings.local.json に入れる。既にファイルがあるなら、hooks の部分だけ足す（手元の Claude Code に「これを settings.local.json に足して」と頼めば早い）
3. 前に check_hook.sh を登録していたら、その行は消す

動き
- outputs\x_articles\ 直下の .md が保存されたときだけ post_article.py <記事> --check を走らせる
- --check が 0 以外で終わったら、その出力を Claude Code に返して直させる
- _factcheck\ の主張台帳や、ほかのフォルダのファイルでは動かない
- post_article.py が無いときは警告だけ出して止めない

前提：--check は指摘があると 0 以外で終わる作り。指摘を出しても 0 で終わる版の post_article.py だと、このフックは何も返さない。そのときは元の check_hook.sh を手元の Claude Code に見せて「check_hook.py を同じ判定に合わせて」と頼む。

## 3. CLAUDE.md への追記

CLAUDE_md_追記.md の枠の中身を CLAUDE.md の末尾に貼る。次の会話から効く。

## 4. --user 必須化

user必須化_貼り付け文.md の枠の中身を、手元の Claude Code に貼る。差分を見せてくるので、確認して OK を出す。

## このセットでは直らないもの

- 402（X API の残高切れ）… developer.x.com でチャージする
- Copilot に話しかけていた … 星マークのパネル（Claude Code）に切り替える
- ZIP が古い … 最新版はほしのから受け取る。setup_check.ps1 が「最新版 ZIP 待ち」と出す項目がそれ
