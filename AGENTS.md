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
├─ .gitignore             ← cookie.txt / __pycache__ 等を除外
├─ cookie.txt             ← 認証情報（コミット禁止・各自で用意）
├─ nicoids.py             ← ツール: シリーズ/マイリスト/検索結果の動画情報エクスポート
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
| `nicoids.py` の使い方・`cookie.txt` の作り方（利用者向け） | [`docs/nicoids-manual.md`](docs/nicoids-manual.md) |
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
5. 認証が要る機能はフォルダ直下の **`cookie.txt`** を読む（`user_session` の値のみ。詳細は API ナレッジ）。
6. エラーは握りつぶさず、日本語で状態表示／ダイアログに出す。
7. コミット前に `__pycache__` や一時ファイルを消す。`cookie.txt` が追跡されていないことを `git status` で確認する。

## 実行方法

```powershell
cd T:\CodeProject\nicotools
python nicoids.py          # GUI が起動する
```

## 動作確認の基本

- ネットワーク系の関数（`fetch_*` など）は GUI を挟まず単体で呼べる。テストは一時スクリプトを作って実行し、**終わったら削除**する。
- GUI のスモークテストは `App()` を生成 → `update()` → `destroy()` で行える。
- シリーズは認証不要のため、疎通確認の定番として `series/62864`（12件）を使うとよい。
