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
├─ cookie.txt             ← 任意。無くても GUI の「ログイン設定…」で代用可（コミット禁止）
├─ nicoids.py             ← ツール: シリーズ/マイリスト/検索結果の動画情報エクスポート
├─ tests/
│  └─ test_nicoids.py     ← 単体テスト（ネットワーク不要・ダミー値のみ）
└─ docs/
   ├─ nicovideo-api.md    ← ニコ動 API / スクレイピングの再利用ナレッジ
   ├─ nicoids.md          ← nicoids.py の仕様・設計メモ・テスト手順（開発者向け）
   └─ nicoids-manual.md   ← nicoids.py の使い方ガイド（利用者向け）
```

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
5. 認証が要る機能は、GUI の「ログイン設定…」で入力した **`user_session`** を優先して使う。
   未入力ならフォルダ直下の **`cookie.txt`** をフォールバックとして読む（`resolve_session`）。
   セッション値は**メモリ上でのみ**扱い、ログ・ステータス・例外メッセージ・**確認コマンドの出力**に
   絶対に含めない（詳細は「動作確認の基本」）。
6. エラーは握りつぶさず、日本語で状態表示／ダイアログに出す。
7. コミット前に `__pycache__` や一時ファイルを消す。`cookie.txt` が追跡されていないことを `git status` で確認する。

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
- シリーズは認証不要のため、疎通確認の定番として `series/62864`（12件）を使うとよい。
