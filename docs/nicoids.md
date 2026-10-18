# nicoids.py — 仕様・設計メモ

ニコニコ動画の **シリーズ / マイリスト / 検索結果** から動画情報を取得し、
**TSV（詳細）または ID のみ** で書き出す tkinter GUI ツール。

API や認証の前提は [`nicovideo-api.md`](nicovideo-api.md) を参照。

---

## 1. できること（機能一覧）

| 入力 | 説明 | 認証 |
|---|---|---|
| `/series/{id}` または数字ID | シリーズの動画一覧 | 不要 |
| `/mylist/{id}`・`/user/{uid}/mylist/{id}` | マイリストの動画一覧 | **必要**（ログイン設定 or `cookie.txt`） |
| `/tag/...`・`/search/...` | 検索結果の動画一覧 | 不要 |

- 種類は「自動判定」のままで URL から判別する（数字のみはシリーズ扱い）。
- 取得 → 結果を一覧表示 → **コピー** / **ファイルに保存**。
- **最大件数**の指定、および取得中の **中断**（ここまでの結果を表示）。
- マイリストの認証は **GUI の「ログイン設定…」で `user_session` を保存**する方式。
  保存先は同フォルダの `cookie.txt`（`resolve_session` が読む）。既定では保存されず、
  ダイアログで「保存する」を押したときだけ書き込む（平文・値のみ1行）。
  「ログイン情報を削除する」で保存済みを消せる。

## 2. 画面と操作

```
URL: [.............................................] [取得] [中断]
種類: [自動判定▼]   □ 数値のみ (so/sm を外す)          [ログイン設定…] ログイン: 未設定
出力形式: (●)TSV（詳細） ( )IDのみ   □ ヘッダ行を付ける
最大件数: [    ] 件 （空欄＝制限なし／検索は約5,000件が上限）
┌──────────────────────────────────────────────────┐
│ （結果。TSV または ID の一覧）                      │
└──────────────────────────────────────────────────┘
[コピー] [ファイルに保存]
状態: 12件取得しました。
```

「ログイン設定…」は `LoginDialog`（モーダル）を開く。状態ラベルは `未設定` /
`設定済み（cookie.txt）` / `cookie.txt を読み取れません` / `要再ログイン` を表示する。

ダイアログの構成（ボタンは「何が起きるか」が分かる文言にしている）:

```
┌ ログイン設定 ─────────────────────────────────────────┐
│ マイリストの取得に使う user_session を入力します。      │
│ [入力欄（●でマスク。80〜90文字が入る幅）   ] [クリア]  │
│ □ 値を表示する                                        │
│ 「保存する」と、nicoids.py と同じフォルダの cookie.txt  │
│ に平文で書き込まれます。                               │
│ [ログイン情報を削除する]      [保存する] [キャンセル]   │
└───────────────────────────────────────────────────────┘
```

- `action`: `"save"` / `"delete"` / `None`（キャンセル）。
- 「クリア」は**入力欄を空にするだけ**（ダイアログは閉じない。保存済みファイルにも触らない）。
- 「ログイン情報を削除する」は常に表示（保存が無ければ「ありません」と状態表示するだけ）。
- `Return` = 保存、`Esc` = キャンセル。

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
  ├ mylist のとき _ensure_session() → 無ければ誘導ダイアログ → open_login_dialog()
  ├ self._cancel.clear()
  └ 別スレッドで _worker(kind, ident, max_items, session)
        └ fetch_series / fetch_mylist / fetch_search
              → (videos, total, reason)
        └ self.after(0, _success, videos, total, reason)   # UI更新は必ずメインスレッドで
  _success() → render() → 状態表示
```

- `_ensure_session()` は **メインスレッドで** `resolve_session()` を評価する。
  未設定ならスレッドを起こす前に設定ダイアログへ誘導し、`None` を返して取得を中止する。
- セッション解決だけは `_worker` から追い出してある（未設定時に無駄なスレッドを作らないため）。

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
| `extract_user_session` / `load_user_session` | `cookie.txt` から `user_session` を取り出す（`load_user_session(paths=)` でテスト用に検索先を差し替え可。既定の候補は `script_dir()/cookie.txt` **のみ**＝カレントディレクトリは見ない） |
| `cookie_file_candidates` / `cookie_file_path` | 読み書きの対象。**保存・削除・有無確認・読み取りを同じ1箇所に揃える**ため `script_dir()/cookie.txt` だけ |
| `is_user_session_value(value)` | `user_session_<数字>_<トークン>` 形式かの検証（ダイアログの入力チェック用） |
| `resolve_session()` | cookie.txt から使う `user_session` を決める。`(value, source)` を返す（`"cookie"` / `"invalid_cookie"` / `None`） |
| `cookie_file_path` / `has_saved_session` | 保存先（`script_dir()/cookie.txt`）と、保存済みの有無 |
| `save_user_session` / `delete_saved_session` | `cookie.txt` への保存（平文・値のみ1行・一時ファイル経由で置換）と削除。保存先は固定で任意パスは受け付けない |
| `LoginDialog` | ログイン設定のモーダル。入力は `extract_user_session` で正規化し、`is_user_session_value` で形式検証（不一致は警告して閉じない）。`action`（`"save"`/`"delete"`/`None`）と `value` で結果を返す |
| `App._ensure_session` / `update_login_indicator` / `open_login_dialog` / `_save_session` / `_delete_saved_session` | mylist 実行前の解決・状態ラベル更新・ダイアログの多重生成防止つき表示・保存/削除の実行 |
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

5. **モーダルダイアログは `grab_set` と多重生成に注意**
   - `LoginDialog` は `transient(self)` + `grab_set()` でモーダル化。`destroy()` で grab は自動解放される。
   - `self._login_dlg` を保持し、`open_login_dialog()` 冒頭で `winfo_exists()` を確認して
     二重に開かない（`wait_window` の入れ子を防ぐ）。
   - 新しい行・ボタンを足すときは、既存の pack 順（落とし穴1）を崩さないこと。
     「ログイン設定…」ボタンと状態ラベルは **`opts` 行の右端（`side="right"`）** に置いている。

## 5. 既知の制限

- 検索結果は **157ページ（約5,024件）が上限**。それ以上はニコ動側がエラーを返す。
- 検索は 32件/ページ固定なので、多件数は時間がかかる（上限指定・中断で短縮可能）。
- マイリスト取得は認証が必須。GUI の「ログイン設定…」で `user_session` を保存する。
  403 のときはセッション切れを疑う（状態ラベルが `要再ログイン` になる）。
- **複数アカウントは非対応**（`cookie.txt` は1つだけ）。セッションの事前有効性チェックも行わない
  （403 を検知して再入力を促す方針）。
- 検索ページの HTML 構造（`<meta name="server-response">`）に依存。仕様変更時は
  `extract_embedded_json` と `fetch_search` のパスを要修正。
- 認証情報は「保存する」を押したときだけ `script_dir()/cookie.txt` に**平文**で保存する
  （保存先は固定。暗号化はしない）。メモリ上だけで使う経路は用意していない。

## 6. テスト手順

**単体テストは `tests/` に常設**（ネットワーク不要・ダミー値のみ）。

```powershell
python -m unittest discover -s tests
```

**ネットワーク取得の疎通確認だけ**は一時スクリプトを作って実行し、**確認後は削除**する（コミットしない）。

```python
import nicoids as n

# 取得（認証不要のシリーズで疎通確認）
v, t, r = n.fetch_series("228685")                 # 16件, r=None
v, t, r = n.fetch_series("228685", max_items=5)    # 5件, r="max_items"
v, t, r = n.fetch_search(url, should_stop=lambda: True)  # 1ページで r="cancelled"

# 整形・認証解決
n.format_duration(1420)      # "23:40"
n.format_duration(3661)      # "1:01:01"
n.extract_user_session("user_session=user_session_1234_xxx")  # "user_session_1234_xxx"
n.resolve_session()[1]       # "cookie" / "invalid_cookie" / None（source だけ見る）

# 保存・削除（保存先は script_dir()/cookie.txt に固定）
n.has_saved_session()        # True / False
n.save_user_session("user_session_1234_xxx")   # 平文・値のみ1行で保存
n.delete_saved_session()     # 削除（無ければ False）

# GUI スモークテスト
app = n.App(); app.update_idletasks(); app.destroy()
```

- 取得関数は GUI を挟まず単体で呼べる。**実トークンをスクリプトに直書きしない**。
- `resolve_session()` の**値**を print すると、実 `cookie.txt` がある環境では実トークンが
  出力に残る。確認は `[1]`（source）だけを見るなど、**値を出さない**こと。
- 日本語の確認は Windows コンソールだと文字化けするので、**結果をファイルに書いて確認**する。

## 7. 変更履歴

- 初版: シリーズ / マイリストから動画IDを改行区切りで出力。
- TSV（詳細）モード・数値のみ・ヘッダ行・mm:ss を追加。
- 結果欄のフォント自動選択、ステータス行のレイアウト修正。
- 検索結果URL（`/tag/`・`/search/`）対応（埋め込みJSONを利用）。
- 最大件数の指定と中断機能を追加。
- マイリストの認証を **GUI の「ログイン設定…」ダイアログ**方式に変更（`cookie.txt` は任意のフォールバック）。
  認証解決を `resolve_session` に分離し、`tests/` を新設。公開向けに README / LICENSE を追加。
- ログイン設定を **「保存する」／「ログイン情報を削除する」／「キャンセル」** の
  3ボタンに整理（`OK`＋チェックボックスの二重表現をやめた。`クリア` は入力欄の右へ移動）。
  メモリ上だけのセッションを廃止し、`cookie.txt` に一本化（`resolve_session` から `gui_value` を削除）。
  入力欄を 96 文字幅に拡大し、ダイアログをリサイズ可能にした。
- `cookie.txt` の読み書きを `script_dir()` の1箇所に統一（カレントディレクトリは見ない）。
  保存は一時ファイル経由の置換にし、403 後の保存/削除で「要再ログイン」表示を正しく解除する。
