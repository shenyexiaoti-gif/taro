# CLAUDE.md

このリポジトリで Claude Code（Cloud sessions を含む）が作業する際の行動規約である。
詳細な運用設計は `docs/cloud-sessions/DESIGN.md` を参照。

## 規約

1. 作業は必ず指定ブランチで行い、main へ直接 push しない。
2. .env、トークン、Client Secret を生成・コミット・出力しない。伏字で扱う。
3. X API への実通信を行わない。テストはモックで行う。
4. 依存を追加しない。標準ライブラリのみの方針を守る。
5. テストは `python3 -m unittest discover -s x-mcp-oauth/tests` で回す。
6. 1 PR は 1 目的とし、無関係な整形を混ぜない。
7. 報告は `docs/cloud-sessions/DESIGN.md` 第4節の報告項目の形式で PR 本文に書く。

## リポジトリ構成

- `x-mcp-oauth/` X の OAuth 2.0 PKCE 切り分けツールとローカル環境レポート。標準ライブラリのみで動く Python スクリプトと README。
- `x-mcp-oauth/tests/` 上記スクリプトの単体テスト（標準 unittest、実通信なし）。
- `.claude/` Cloud sessions 向けの設定。SessionStart フックと枠ごとの依頼テンプレ（`tasks/`）。
- `docs/cloud-sessions/` 運用設計書と消費ログ。
