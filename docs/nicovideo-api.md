# ニコニコ動画 API / スクレイピング ナレッジ

ニコ動から動画情報を取得するための、再利用できる知識をまとめる。
（検証時期: 2026年。仕様は予告なく変わるため、実装時は必ず一度叩いて確認すること）

---

## 1. 共通事項

### 1.1 nvapi のリクエストヘッダ

`https://nvapi.nicovideo.jp/...` を叩くときの基本ヘッダ:

```http
User-Agent: Mozilla/5.0 ...
Accept: application/json
X-Frontend-ID: 6
X-Frontend-Version: 0
```

- `X-Frontend-Id`（小文字 d）でも通る（HTTP ヘッダは大文字小文字を区別しない）。
- 認証が要る API は上に加えて `Cookie: user_session=<値>` を付ける。

### 1.2 認証（cookie.txt と user_session）

- ログインセッションの Cookie は **名前 `user_session`**、**値は `user_session_<数字>_<トークン>`** という形式。
  - 例: `Cookie: user_session=user_session_83033_xxxxxxxx...`
- このリポジトリでは **`cookie.txt` に「値のみ」を1行で保存**する運用（他ツールと共用）。
  - `cookie.txt` の中身例: `user_session_83033_xxxxxxxx...`
  - 実装は `user_session=...` / Netscape形式 / Cookieヘッダ文字列も解釈できるようにしてある（`extract_user_session`）。
- **`cookie.txt` は絶対にコミットしない**（`.gitignore` 済み）。値は有効なログイン資格情報そのもの。
- 無効・期限切れの場合は API が **HTTP 403 `FORBIDDEN`** を返す。

### 1.3 リトライ

`429 / 500 / 502 / 503 / 504` は指数バックオフで数回リトライする。ページ取得の間にも小さく `sleep` を入れる（0.2〜0.3 秒）。

---

## 2. シリーズ

**認証不要。**

```
GET https://nvapi.nicovideo.jp/v2/series/{seriesId}?pageSize=100&page={n}&sensitiveContents=mask
```

レスポンス（抜粋）:

```jsonc
{
  "data": {
    "detail": { "id": 62864, "title": "...", "owner": { "id": "ch...", "name": "..." } },
    "totalCount": 12,
    "items": [
      {
        "meta": { "id": "so33963154", "order": 1 },
        "video": {
          "id": "so33963154",
          "title": "ゾンビランドサガ 第1話 ...",
          "registeredAt": "2018-10-07T22:00:00+09:00",
          "duration": 1420,
          "count": { "view": 107373, "comment": 2569, "mylist": 1792, "like": 334 },
          "thumbnail": { "url": "...", "largeUrl": "...", "nHdUrl": "..." },
          "shortDescription": "...",
          "owner": { "id": "ch2632720", "name": "..." }
        }
      }
    ]
  }
}
```

- ページング: `page` を 1,2,... と進める（`pageSize=100` が有効）。`totalCount` に達したら終了。
- 並び順はシリーズの順（`meta.order`）。
- 動作確認用の定番: `series/62864`（12件）。

---

## 3. マイリスト

**認証必須**（`Cookie: user_session=...` が無いと 403）。

```
GET https://nvapi.nicovideo.jp/v2/mylists/{mylistId}?pageSize=100&page={n}
```

レスポンス（抜粋）:

```jsonc
{
  "data": {
    "mylist": {
      "id": 79588643,
      "name": "...",
      "description": "...",
      "totalItemCount": 38,   // ← シリーズの totalCount とは名前が違う
      "hasNext": false,
      "items": [
        {
          "itemId": "...",
          "watchId": "sm46905943",
          "addedAt": "...",
          "video": { "id": "sm46905943", "title": "...", "duration": 257, "count": { ... } }
        }
      ]
    }
  }
}
```

- **総件数は `totalItemCount`**（`totalCount` ではない）。終了判定は `hasNext` を使うと確実。
- items の実体は `items[].video`（`watchId` にも ID がある）。
- `mylistId` は `/mylist/{id}` や `/user/{uid}/mylist/{id}` から取れる。

---

## 4. 検索 / タグ（`/tag/...`・`/search/...`）

**認証不要。ただし専用 API ではなく、HTML に埋め込まれた JSON を読む。**

```
GET https://www.nicovideo.jp/tag/{tag}?sort=f&page={n}
GET https://www.nicovideo.jp/search/{query}?sort=f&page={n}
```

### 4.1 データの在りか

レスポンス HTML の中に、次の `<meta>` がある:

```html
<meta name="server-response" content="{&quot;data&quot;:{...},&quot;meta&quot;:{...}}">
```

- `content` の中身は **HTML エスケープされた JSON**。`html.unescape` してから `json.loads` する。
- 抽出正規表現の例: `<meta\s+name="server-response"\s+content="([\s\S]*?)"\s*/?>`
- たどるパス:

```
data.response.$getSearchVideoV2.data
    ├─ searchId
    ├─ totalCount
    ├─ hasNext
    └─ items[]         ← 動画オブジェクトそのもの（video でラップされていない）
```

### 4.2 制約

- **1ページ固定 32件**。`pageSize` クエリを付けても無視される。
- **ページ上限は 157**。158ページ目以降は次のエラーノードが返る:
  ```json
  { "error": { "heading": "指定可能なページ数の上限を超えています", "message": "..." } }
  ```
  → 実質 **最大 157 × 32 = 5,024 件** まで。`totalCount` がこれを超えても全件は取れない。
- `sort=f` などのクエリパラメータはそのまま尊重される（並び順に反映）。
- 多数ページを取ると時間がかかる（157ページ ≒ 1〜2分）。**上限件数の指定 or 中断**を用意するとよい。

### 4.3 URL のエンコード

- 日本語タグは URL エンコードが必要。**タグ中の半角スペースは `+`** にする（ニコ動の慣習）。
- 既にエンコード済みの `%xx` や、除外指定の `-`、AND の `+` は**壊さない**こと。
- 実装例（`nicoids.py` の `normalize_search_url`）: 非ASCIIのみ `urllib.parse.quote`、半角スペースは `+`。

---

## 5. 動画オブジェクトの主なフィールド

シリーズの `video`、マイリストの `items[].video`、検索の `items[]` はほぼ同じ形:

| フィールド | 内容 |
|---|---|
| `id` | 動画ID（`sm` / `so` / `nm` / `ss` など） |
| `title` | タイトル |
| `registeredAt` | 投稿日時（ISO8601） |
| `duration` | 再生時間（**秒**） |
| `count.view` | 再生数 |
| `count.comment` | コメント数 |
| `count.mylist` | マイリスト数 |
| `count.like` | いいね数 |
| `owner.id` / `owner.name` | 投稿者 / チャンネル |
| `shortDescription` | 概要（冒頭） |
| `thumbnail.url` ほか | サムネイルURL（複数サイズ） |

---

## 6. ハマりどころ（実体験）

- **マイリストの総件数は `totalItemCount`**。`totalCount` を見ていると常に None になる。
- **検索ページは `data-video-id` では取れない**（`-1` 件）。`<meta name="server-response">` を読むのが正解。
- 検索の埋め込み JSON は**エスケープ済み**なので、`html.unescape` を忘れると `json.loads` が落ちる。
- **検索は 157 ページの壁**がある。大量ヒットの検索結果を「全件」取ろうとすると必ず途中で失敗する。
- `nvapi.nicovideo.jp/v2/search/video/v2` などは 404 で使えない（この用途では HTML 埋め込み JSON が確実）。
- マイリスト API は未ログインだと **403**。Cookie の付け忘れ／期限切れを疑う。
- Windows のコンソール（cp932）に日本語を print すると文字化けするが、**アプリの動作には影響しない**（確認はファイル出力で行うと確実）。
