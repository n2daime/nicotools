# nicoids.py — 仕様・設計メモ

ニコニコ動画の **シリーズ / マイリスト / 検索結果** から動画情報を取得し、
**TSV（詳細）または ID のみ** で書き出す tkinter GUI ツール。

API や認証の前提は [`nicovideo-api.md`](nicovideo-api.md) を参照。

---

## 1. できること（機能一覧）

| 入力 | 説明 | 認証 |
|---|---|---|
| `/series/{id}` または数字ID | シリーズの動画一覧 | 不要 |
| `/mylist/{id}`・`/user/{uid}/mylist/{id}` | マイリストの動画一覧 | **必要**（`cookie.txt`） |
| `/tag/...`・`/search/...` | 検索結果の動画一覧 | 不要 |

- 種類は「自動判定」のままで URL から判別する（数字のみはシリーズ扱い）。
- 取得 → 結果を一覧表示 → **コピー** / **ファイルに保存**。
- **最大件数**の指定、および取得中の **中断**（ここまでの結果を表示）。

## 2. 画面と操作

```
URL: [.............................................] [取得] [中断]
種類: [自動判定▼]   □ 数値のみ (so/sm を外す)
出力形式: (●)TSV（詳細） ( )IDのみ   □ ヘッダ行を付ける
最大件数: [    ] 件 （空欄＝制限なし／検索は約5,000件が上限）
┌──────────────────────────────────────────────────┐
│ （結果。TSV または ID の一覧）                      │
└──────────────────────────────────────────────────┘
[コピー] [ファイルに保存]
状態: 12件取得しました。
```

### 出力形式

- **TSV（詳細）**: `動画ID <TAB> タイトル <TAB> 再生数 <TAB> コメント数 <TAB> 再生時間`
  - 再生時間は `mm:ss`（1時間以上は `h:mm:ss`）。
  - タイトル内のタブ・改行・連続空白は**1つの半角スペース**に整形（列ズレ防止）。
  - 「ヘッダ行を付ける」ON で先頭に列名行を付与。
- **IDのみ**: 動画IDを改行区切り。
- 「数値のみ」ON で `so33963154` → `33963154`（TSV のID列にも適用）。
- 保存の既定名: TSV → `nicovideo.tsv` / IDのみ → `ids.txt`（UTF-8・LF）。

### 状態メッセージ

| 状況 | 表示 |
|---|---|
| 全部取得 | `N件取得しました。` |
| 最大件数で終了 | `N件取得しました（指定した最大件数に達したため終了）。` |
| 中断 | `中断しました（N件）。` |
| 検索の上限で打ち切り | `N件取得しました（全X件。上限等のため途中で打ち切り）。` ＋ 警告ダイアログ |

## 3. 内部設計

### 3.1 データの流れ

```
on_fetch()
  ├ parse_target(text, 種類) → (kind, ident)   kind: "series" / "mylist" / "search"
  ├ self._cancel.clear()
  └ 別スレッドで _worker(kind, ident, max_items)
        └ fetch_series / fetch_mylist / fetch_search
              → (videos, total, reason)
        └ self.after(0, _success, videos, total, reason)   # UI更新は必ずメインスレッドで
  _success() → render() → 状態表示
```

### 3.2 `fetch_*` の戻り値（共通契約）

```python
(videos, total, reason)
```

- `videos`: `list[dict]`。各要素は `{id, title, view, comment, duration, owner, registered_at, description}`。
- `total`: ニコ動側が申告する総件数（不明なら `None`）。
- `reason`: 終了理由。`None`（全部取得） / `"max_items"` / `"cancelled"` / `"page_limit"`。

引数（共通）: `progress=callable(str)`, `should_stop=callable()->bool`, `max_items=int|None`。

> 新しい取得元を足すときは **同じ契約** に合わせること。GUI 側は契約しか見ていない。

### 3.3 主な関数

| 関数 | 役割 |
|---|---|
| `parse_target(text, force_type)` | 入力から `(kind, ident)` を作る。検索は URL 全体を返す |
| `fetch_series` / `fetch_mylist` / `fetch_search` | 取得本体（上記契約） |
| `_video_info_from_item(item)` | API/埋め込みJSONの1件から必要項目を取り出す |
| `http_get_json` / `http_get_text` | リトライ付き GET |
| `extract_embedded_json(html)` | 検索ページの `<meta name="server-response">` を JSON 化 |
| `normalize_search_url` / `set_query_param` | 検索URLのエンコードと `page` 付与 |
| `extract_user_session` / `load_user_session` | `cookie.txt` から `user_session` を取り出す |
| `format_duration` / `format_count` / `sanitize_cell` / `strip_prefix` | 表示用の整形 |
| `pick_text_font` | 結果欄のフォント自動選択 |

### 3.4 定数

| 名前 | 値 | 意味 |
|---|---|---|
| `PAGE_SIZE` | 100 | シリーズ/マイリストのページ取得件数 |
| `SEARCH_PAGE_SIZE` | 32 | 検索の1ページ件数（ニコ動側固定・参考値） |
| `SEARCH_MAX_PAGE` | 157 | 検索のページ上限（≒5,024件） |
| `FONT_CANDIDATES` | リスト | 結果欄フォントの優先順 |

## 4. GUI の落とし穴（過去にハマった点）

1. **`pack` の順序でウィジェットが潰れる**
   - 結果欄の `Text` は要求高さが大きい。`Text` を先に `expand` で詰めると、後から `pack` した
     ステータス行が 3px に潰れて見えなくなる。
   - 対策: **下側（ボタン行・状態行）を `side="bottom"` で先に確保**し、中央の結果欄を
     **最後に `side="top", fill="both", expand=True`** で配置する。

2. **日本語が太字っぽくなる**
   - `Consolas` 等の日本語非対応フォントを指定すると、Windows のフォントフォールバックで
     日本語が合成表示され、太字のように見える。
   - 対策: `pick_text_font` で Windows 標準の日本語フォント（`Meiryo UI` → `Yu Gothic UI` →
     `ＭＳ ゴシック` …）を優先採用する。

3. **UI 更新はスレッドから直接触らない**
   - 取得は別スレッド。UI 更新は `self.after(0, ...)` 経由でメインスレッドに行う。

4. **中断はページの区切りでしか効かない**
   - `threading.Event` をループ先頭で確認する方式。1リクエストの途中では止まれない。

## 5. 既知の制限

- 検索結果は **157ページ（約5,024件）が上限**。それ以上はニコ動側がエラーを返す。
- 検索は 32件/ページ固定なので、多件数は時間がかかる（上限指定・中断で短縮可能）。
- マイリスト取得は `cookie.txt` が必須。403 のときはセッション切れを疑う。
- 検索ページの HTML 構造（`<meta name="server-response">`）に依存。仕様変更時は
  `extract_embedded_json` と `fetch_search` のパスを要修正。

## 6. テスト手順

一時スクリプトを作って実行し、**確認後は削除**する（コミットしない）。

```python
import nicoids as n

# 取得（認証不要のシリーズで疎通確認）
v, t, r = n.fetch_series("62864")                 # 12件, r=None
v, t, r = n.fetch_series("62864", max_items=5)    # 5件, r="max_items"
v, t, r = n.fetch_search(url, should_stop=lambda: True)  # 1ページで r="cancelled"

# 整形
n.format_duration(1420)      # "23:40"
n.format_duration(3661)      # "1:01:01"
n.extract_user_session("user_session_83033_xxx")  # "user_session_83033_xxx"

# GUI スモークテスト
app = n.App(); app.update_idletasks(); app.destroy()
```

- 取得関数は GUI を挟まず単体で呼べる。
- 日本語の確認は Windows コンソールだと文字化けするので、**結果をファイルに書いて確認**する。

## 7. 変更履歴

- 初版: シリーズ / マイリストから動画IDを改行区切りで出力。
- TSV（詳細）モード・数値のみ・ヘッダ行・mm:ss を追加。
- 結果欄のフォント自動選択、ステータス行のレイアウト修正。
- 検索結果URL（`/tag/`・`/search/`）対応（埋め込みJSONを利用）。
- 最大件数の指定と中断機能を追加。
