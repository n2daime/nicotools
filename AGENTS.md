# AGENTS.md

このリポジトリは **ニコニコ動画まわりの簡易ツールを置く場所** です。
各ツールは「1ファイルで完結する Python スクリプト（GUI は tkinter）」を基本とします。

## 対象・前提

- OS: Windows（開発機は日本語環境）
- Python: 3.12（**標準ライブラリのみ**。追加インストールは行わない）
- 出力・UI は日本語
- `cookie.txt` などの認証情報は**絶対にコミットしない**（`.gitignore` 済み）

## ディレクトリ構成

```
nicotools/
├─ AGENTS.md              ← このファイル（入口・開発ルール）
├─ README.md              ← 利用者向けの入口（公開ページ）
├─ LICENSE                ← MIT
├─ .gitignore             ← cookie.txt / 出力物 / __pycache__ 等を除外
├─ .github/
│  └─ workflows/
│     └─ release.yml      ← タグ push でリリースを自動発行（nicoids.py を添付）
├─ cookie.txt             ← ログイン設定の保存先（GUI から作成。コミット禁止）
├─ nicoids.py             ← ツール: シリーズ/マイリスト/検索結果の動画情報エクスポート
├─ tests/
│  └─ test_nicoids.py     ← 単体テスト（ネットワーク不要・ダミー値のみ）
└─ docs/
   ├─ nicovideo-api.md    ← ニコ動 API / スクレイピングの再利用ナレッジ
   ├─ nicoids.md          ← nicoids.py の仕様・設計メモ・テスト手順（開発者向け）
   └─ nicoids-manual.md   ← nicoids.py の使い方ガイド（利用者向け）
```

**配布物（リリースに添付するもの）は `nicoids.py` だけ。**
`docs/` `tests/` `AGENTS.md` は開発用で、利用者には渡さない（「リリース手順」参照）。

## ナレッジへの導線

| 知りたいこと | 参照先 |
|---|---|
| ニコ動の API エンドポイント・認証・ページング・上限 | [`docs/nicovideo-api.md`](docs/nicovideo-api.md) |
| `nicoids.py` の仕様・設計・テスト・既知の制限（開発者向け） | [`docs/nicoids.md`](docs/nicoids.md) |
| `nicoids.py` の使い方・ログイン設定（`user_session`）の説明（利用者向け） | [`docs/nicoids-manual.md`](docs/nicoids-manual.md) |
| 新ツールを作るときの共通ルール | このファイルの下記「開発ルール」 |

**利用者向けの説明書を書くときは `docs/nicoids-manual.md` の構成・トーンに合わせる。**
ツールの使い方や仕様が変わったら、`docs/nicoids.md`（開発者向け）と
`docs/nicoids-manual.md`（利用者向け）の両方を更新する。

**新しいツールを作る／直す前に、まず `docs/nicovideo-api.md` を読むこと。** 認証やページングの落とし穴がまとまっています。

## 開発ルール

1. **標準ライブラリのみ**。`pip install` が必要な実装は避ける（`urllib` / `tkinter` / `json` / `re` / `html` など）。
2. **1ツール = 1スクリプト**（例: `nicoids.py`）。共通化が必要になるまでは依存を増やさない。
3. GUI は `tkinter`。日本語が正しく表示されるフォントを選ぶ（[`docs/nicoids.md`](docs/nicoids.md) の「GUIの落とし穴」参照）。
4. ネットワーク取得は別スレッドで行い、GUI を固まらせない。中断（`threading.Event`）と件数上限に対応させる。
5. 認証が要る機能は、GUI の「ログイン設定…」で **保存した `user_session`** を使う（`resolve_session`）。
   **既定では保存しない**。ダイアログの「保存する」を押したときだけ
   `save_user_session` で `script_dir()/cookie.txt` に**平文**で保存する（保存先は固定・任意パス不可）。
   「ログイン情報を削除する」で `delete_saved_session` により削除できる。
   セッション値はログ・ステータス・例外メッセージ・**確認コマンドの出力**に絶対に含めない
   （詳細は「動作確認の基本」）。
6. エラーは握りつぶさず、日本語で状態表示／ダイアログに出す。
7. コミット前に `__pycache__` や一時ファイルを消す。`cookie.txt` が追跡されていないことを `git status` で確認する。
8. HTTP の `User-Agent` は `USER_AGENT` 定数（`WeeklyNicoranProgram`）を使う。
   ニコ動の担当者から「識別できるツール名にしてほしい（日本語文字は入れない）」と依頼されているため、
   **ブラウザ偽装に戻したり勝手に変えたりしない**（詳細は [`docs/nicovideo-api.md`](docs/nicovideo-api.md) の「User-Agent」）。

## 実行方法

```powershell
python nicoids.py          # GUI が起動する（リポジトリ直下で）
```

## 動作確認の基本

- 整形・URL 解析・認証解決などの**単体テストは `tests/` に常設**。リポジトリ直下で実行する。

  ```powershell
  python -m unittest discover -s tests
  ```

- **ネットワーク取得の疎通確認だけ**は一時スクリプトを作って実行し、**終わったら削除**する（コミットしない）。実トークンはスクリプトに書かない。
- **確認コマンドの出力に実セッション値を出さない。** `cookie.txt` がある環境では
  `resolve_session(None)` や `load_user_session()` が**実トークンを返す**。値を print すると
  端末ログ・セッション記録に残ってしまう。確認するときは `[1]`（source）だけを見る、
  `is_user_session_value()` の真偽だけを見る、など**値を出力しない**こと。
  （うっかり出力してしまったら、ニコニコからログアウト→再ログインでセッションを無効化する。）
- GUI のスモークテストは `App()` を生成 → `update()` → `destroy()` で行える（`tests/` にも入っている）。
- シリーズは認証不要のため、疎通確認の定番として `series/228685`（16件）を使うとよい。

## リリース手順

配布するのは **`nicoids.py` だけ**。タグを push すると GitHub Actions
（[`.github/workflows/release.yml`](.github/workflows/release.yml)）がテストを実行し、
成功したら `nicoids.py` を添付したリリースを自動で作る。

1. `nicoids.py` の `__version__` を上げる（例: `1.0.0` → `1.1.0`）。
2. `docs/nicoids-manual.md` の変更履歴に追記する。
3. `python -m unittest discover -s tests` を通す。
4. `main` にコミットして push する。
5. **タグを打って push する**（ここで Actions が動く）。

   ```powershell
   git tag v1.1.0
   git push origin v1.1.0
   ```

6. `gh run watch` で結果を確認し、Releases に `nicoids.py` が付いたことを見る。

- **タグ（`v1.1.0`）と `__version__`（`1.1.0`）が一致しないとリリースは失敗する**（付け忘れ防止）。
- 失敗したらタグを消してやり直す: `git push origin :v1.1.0` → `git tag -d v1.1.0` → 直して再 push。
- 手元で同じことをする場合:

  ```powershell
  gh release create v1.1.0 nicoids.py --title v1.1.0 --generate-notes
  ```

- README のダウンロード導線は `releases/latest` を指しているので、リリースを出せば自動で最新になる。
- 配布物には `LICENSE` を含めない代わりに、`nicoids.py` の先頭に著作権と MIT の案内を書いている。
