"""X記事下書きのカバー画像を、画像対応表CSVに従って一括差し替えする。

使い方（Windowsローカル）:
  pip install playwright
  python update_covers.py 2026-10-07_5記事_画像対応表_v02.csv
  python update_covers.py 対応表.csv --dry-run   # 対象確認だけ

初回はブラウザが開くのでXに手動ログインする。ログイン状態は .x-profile に保存される。
各下書きで画像をセットした後、画面を目視確認してEnterで次へ進む（自動保存任せ）。
X側の画面構成が変わるとセレクタが外れるので、その場合は手動アップロードに切り替える。
"""
import argparse
import csv
import sys
from pathlib import Path

EDIT_URL = "https://x.com/compose/articles/edit/{draft_id}"


def load_covers(csv_path):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("kind") == "サムネ"]
    for r in rows:
        if not Path(r["path"]).is_file():
            sys.exit(f"画像が見つからない: {r['path']}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    covers = load_covers(args.csv)
    for r in covers:
        print(f"{r['article']:<10} {r['draft_id']}  {Path(r['path']).name}")
    if args.dry_run:
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(Path(__file__).with_name(".x-profile")), headless=False, channel="chrome"
        )
        page = ctx.new_page()
        page.goto("https://x.com/home")
        input("Xにログイン済みならEnter > ")

        for r in covers:
            page.goto(EDIT_URL.format(draft_id=r["draft_id"]))
            page.wait_for_load_state("networkidle")
            # 既存カバーの削除ボタンがあれば先に外す（無ければスキップ）
            remove = page.locator('[aria-label*="Remove"], [aria-label*="削除"]').first
            if remove.count():
                remove.click()
            file_input = page.locator('input[type="file"]').first
            file_input.set_input_files(r["path"])
            ans = input(f"[{r['article']}] 反映を確認したらEnter / 失敗なら s でスキップ > ")
            print("  スキップ" if ans.strip() == "s" else "  完了")

        ctx.close()


if __name__ == "__main__":
    main()
