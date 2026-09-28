# X MCP の OAuth 2.0 が繋がらない件 ── 切り分け手順

## 結論から

OAuth 1.0a で今動いているなら、そのまま使い続けてよい。X は 1.0a User Context を現行でもサポートしており、
自分のアカウント1つを MCP から操作するだけの構成なら、Access Token / Secret 方式のほうが素直である。
2.0 への移行は「複数ユーザーに X MCP を提供する」段になってから効いてくる話。

ただし 1.0a のまま運用するなら、最低限これは守る。

- API Key / Secret、Access Token / Secret をコードに直書きしない（.env か Secret Manager）
- MCP に公開する操作を必要最小限に絞る
- 投稿・削除など不可逆な操作は、AI に自走させず投稿前の承認を挟む

そのうえで、2.0 の接続は裏で直す。以下がその手順。

## MCP から X を操作する（npm 不要）

1.0a の鍵が通ったら、その鍵で X を操作する MCP サーバーをこのフォルダの Python で建てられる。
npm パッケージを落とさないので、外部実行ファイルを消すタイプのセキュリティ製品に引っかからない。

```powershell
cd x-mcp-oauth
powershell -ExecutionPolicy Bypass -File .\run_oauth1.ps1   # 先に 1.0a を通しておく
powershell -ExecutionPolicy Bypass -File .\setup_mcp.ps1    # Claude の設定に登録する
```

`setup_mcp.ps1` は、疎通を確認したうえで設定ファイルをバックアップし、`mcpServers` に `x-oauth1` を追記する。
秘密の値は設定ファイルに書かない。サーバーが同じフォルダの `.env` から読む。
登録先を変えるなら `-ConfigPath "パス"`、書き込まず内容だけ見るなら `-Print`。

登録後に Claude を再起動すると、次の3つが使える。

| ツール | 種別 | 内容 |
|---|---|---|
| x_get_me | 読み取り | 自分のアカウント情報を返す |
| x_search_recent | 読み取り | 直近7日のポストを検索する |
| x_post_tweet | 書き込み | ポストを1件投稿する。実行前に承認を挟む |
| x_delete_tweet | 書き込み | 指定 id のポストを削除する。テスト投稿の後始末に使う |

投稿は不可逆なので、`x_post_tweet` は必ず内容を確認してから実行する。Claude 側の許可プロンプトがその関所になる。

## 1.0a で繋ぐ（自分のアカウント1つならこちら）

ブラウザでの承認も Callback も PKCE も要らない。Developer Portal で発行した4つの値を .env に入れ、
署名付きリクエストを1本送るだけで結果が出る。

```powershell
cd x-mcp-oauth
powershell -ExecutionPolicy Bypass -File .\run_oauth1.ps1
```

Windows 以外なら `python3 x_oauth1_check.py`。叩くのは `GET /2/users/me` の1回だけで、投稿はしない。
出力は `oauth1_result.txt` にも残る。秘密の値は伏字なので、そのまま貼ってよい。

発行の順番だけは守る。App permissions を Read and write にしてから Access Token を発行する。
逆だと読み取り専用のトークンが残る。権限を変えたら Access Token を再発行する。

| 症状 | 疑うもの |
|---|---|
| HTTP 0（届かない） | ネット接続、プロキシ、ファイアウォール |
| 401 | 4つの値の取り違え、再発行前の古い値、手元の時計のずれ |
| 403 | App が Project に紐づいていない、プラン・権限の不足 |
| 402 | クレジット・利用枠の不足（署名は通っている） |
| 200 だが投稿できない | 権限が Read のまま。上の順番で Access Token を再発行 |

署名の実装は、X 公式ドキュメント「Creating a signature」の例と同じ値が出ることをテストで確認済み。

## なぜ 2.0 だけ繋がらないのか

X の OAuth 2.0 は Client ID を入れて終わりではなく、Authorization Code Flow + PKCE である。
工程が5つに割れており、どの工程で落ちたかを特定しないと直しようがない。

```
① 認可URLの組み立て        client_id / redirect_uri / scope / code_challenge
        ↓
② X の承認画面             ここが出ないなら ① の問題
        ↓
③ redirect_uri へ戻る      戻らないなら Callback URI の不一致
        ↓
④ code を token に交換     ここが最頻の落とし穴（client認証・code_verifier・期限）
        ↓
⑤ Refresh Token で更新     ローテーション未対応だと2回目で死ぬ
```

## 容疑者リスト

### 1. Callback URL / Redirect URI の不一致

X は Redirect URI の完全一致（exact match）を要求する。
`https://example.com/callback` と `https://example.com/callback/` は別物として扱われる。
末尾スラッシュ、http と https、ポート番号、大文字小文字、すべて。

同梱ツールはこのズレを実際に再現できる。パスが1文字違うだけでコールバックが 404 になる様子が出る。

### 2. Confidential client と Public client の取り違え

貼られた診断で抜けていたのがここ。Developer Portal の Type of App で挙動が変わる。

| Type of App | クライアント種別 | トークン交換時 |
|---|---|---|
| Web App, Automated App or Bot | Confidential | client_id:client_secret を Basic 認証ヘッダで送る |
| Native App | Public | client_secret を送らない。client_id をボディに入れる |

MCP サーバーの実装が Public client 前提なのに Portal 側が Web App になっていると、
承認画面までは通り、④ の交換で 401 が返る。症状が「認証画面は出るのに最後で失敗」と一致するため、
PKCE の不具合と誤診されやすい。

### 3. PKCE の持ち回り

`code_verifier` を生成した工程と、トークン交換する工程が別プロセス・別リクエストになっているとき、
verifier が引き継がれず、新しく生成し直してしまう実装がある。これも ④ で `invalid_grant` になる。

`code_challenge_method` は S256 を使う。同梱ツールは RFC 7636 の検証ベクタで生成ロジックを確認済み。

### 4. Scope

投稿するなら `tweet.read` `tweet.write` `users.read`。区切りは半角スペースで、カンマ区切りは通らない。
MCP から常駐で動かすなら `offline.access` が要る。これが無いと Refresh Token が発行されず、
アクセストークンの期限が切れた時点で沈黙する。

App permissions が Read only のままだと、scope に tweet.write を書いても書き込み権限は降りてこない。
Portal 側で権限を変更した場合、既存のトークンは無効になるので認可からやり直す。

### 5. 認可コードの有効期限

認可コードは短命で、X のドキュメントでは30秒と案内されている。
リダイレクト後のトークン交換が詰まると、そこで期限切れになる。
同梱ツールはリダイレクトから交換完了までの実測秒数を出すので、これが原因かどうかは数字で判定できる。

数値そのものは変わり得るため、判断の前に X の現行ドキュメントで確認すること。

### 6. Refresh Token のローテーション

X は更新のたびに新しい Refresh Token を返し、古いものを無効化する。
返ってきた新しい値を保存し直さない実装だと、初回は成功して2回目の更新で必ず落ちる。
「しばらく動いていたのに数時間後に死ぬ」という症状はこれ。

## まず手元の実物を読む

クラウド側のセッションからは、あなたのマシンの MCP 設定は見えない。
先に手元でこれを走らせて、実物のレポートを取る。

```bash
python3 local_env_report.py
```

読み取り専用で、何も書き換えない。やることは4つ。

- Claude Desktop / Claude Code の設定ファイルを OS ごとの既定パスから探す
  （macOS は `~/Library/Application Support/Claude/claude_desktop_config.json`、
  Windows は `%APPDATA%\Claude\claude_desktop_config.json`、加えて `~/.claude.json` と `.mcp.json`）
- 見つかった MCP サーバーのうち、X / Twitter 関連のものを抜き出す
- その env から OAuth 1.0a 構成か 2.0 構成かを判定し、静的な穴を指摘する
- カレント配下の .env 系にある X 関連キーを、キー名だけ列挙する

秘密の値は伏字にする。redirect_uri と scope だけは原因判定に全文が要るのでそのまま出すが、
どちらも秘密情報ではない。出力はそのまま貼ってよい。

## 使い方（実走）

```bash
cd x-mcp-oauth
cp .env.example .env      # 値を埋める
python3 x_oauth2_pkce_check.py --check-config   # 静的チェック
python3 x_oauth2_pkce_check.py                  # 実走
```

標準ライブラリだけで動く。追加インストールは不要。

### Windows なら一発で

```powershell
cd x-mcp-oauth
powershell -ExecutionPolicy Bypass -File .\run_oauth2.ps1
```

Python の検出、.env の用意、静的チェック、実走（ブラウザは自動で開く）、リフレッシュ検証までを順に進める。
.env が無ければ作ってメモ帳で開き、そこで止まる。値を埋めて保存し、もう一度実行する。
出力は `oauth2_result.txt` にも残る。トークンは伏字なので、そのまま貼ってよい。
redirect_uri が localhost 以外なら `-Manual` を付ける。

`--check-config` は、目で見ても分からないズレを潰す。末尾スラッシュ、前後の空白、全角文字の混入、
scope のカンマ区切り、offline.access の欠落。ここで NG が出るなら実走する意味がない。

実走すると認可URLを吐くので、ブラウザで開いて承認する。redirect_uri が localhost なら、
ツールがローカルで待ち受けてコードを受け取り、そのまま交換まで進む。
localhost 以外なら `--manual` で、戻ってきたURLを手貼りする。

出力にはトークンを伏字で出している。そのまま貼っても秘密は漏れない。

### 落ちたときの読み方

| 症状 | 見るべき容疑者 |
|---|---|
| 承認画面が出ない | 1（client_id）、4（scope の綴り） |
| 承認画面は出るが戻ってこない | 1（Callback URI の登録・完全一致） |
| 戻るが 404 / path mismatch | 1（パスの不一致。末尾スラッシュ） |
| 交換で HTTP 401 | 2（Confidential / Public の取り違え） |
| 交換で invalid_grant | 3（verifier）、5（期限）、1（交換時の redirect_uri） |
| 交換で HTTP 403 | 4（App permissions が Read only） |
| users/me が 403 | 4（users.read の欠落） |
| 数時間後に沈黙 | 6（Refresh Token のローテーション未対応） |

## 移行後の姿

```
Claude / ChatGPT
        ↓
   MCP Server
        ↓
OAuth 2.0 + PKCE + Refresh Token
        ↓
     X API
```

ここまで通ったら、MCP 側の実装を同じ手順に合わせる。
このツールで通って MCP で通らないなら、原因は X 側ではなく MCP サーバーの実装にある、と切り分けが済んだことになる。

## クラウド運用時の注意

`x_oauth2_pkce_check.py` の認可フローの実走と `local_env_report.py` の実走は、どちらも手元のマシンでのみ行う。
前者は X の承認画面とローカルの callback を要し、後者は手元マシンの MCP 設定ファイルを読む道具であり、
クラウド側のセッションからはどちらも実行できない、または実行する意味がない。

.env や実トークンは、クラウドセッションにも、環境の Secrets にも入れない。
クラウド側で回すのは構文チェックとこのリポジトリのテストだけであり、テストは実通信なしで完結する。
