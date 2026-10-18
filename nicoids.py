# -*- coding: utf-8 -*-
"""ニコニコ動画のシリーズ / マイリスト / 検索結果から動画情報を書き出す GUI ツール。

- シリーズ  : 認証不要（nvapi v2/series）
- マイリスト: 「ログイン設定」で保存した user_session を使用（nvapi v2/mylists）。
              保存先は同フォルダの cookie.txt（平文・値のみ1行）。
- 検索結果  : /tag/… ・ /search/… のページに埋め込まれた JSON を利用（認証不要）

出力モード:
- TSV（詳細）: 動画ID / タイトル / 再生数 / コメント数 / 再生時間(mm:ss)
- IDのみ    : 動画IDを改行区切りで出力

標準ライブラリのみで動作します（tkinter / urllib）。
"""

# Copyright (c) 2026 2daime (https://github.com/n2daime)
# MIT License. 全文は同梱の LICENSE、または
# https://github.com/n2daime/nicotools/blob/main/LICENSE を参照。

__version__ = "1.0.0"

import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

API_BASE = "https://nvapi.nicovideo.jp"
PAGE_SIZE = 100
TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

TYPE_AUTO = "自動判定"
TYPE_SERIES = "シリーズ"
TYPE_MYLIST = "マイリスト"

KIND_SERIES = "series"
KIND_MYLIST = "mylist"
KIND_SEARCH = "search"

# 検索結果の1ページあたり件数（ニコニコ側で固定）と、取得可能なページ上限
SEARCH_PAGE_SIZE = 32
SEARCH_MAX_PAGE = 157

MODE_TSV = "TSV（詳細）"
MODE_ID = "IDのみ"
TSV_HEADER = ["動画ID", "タイトル", "再生数", "コメント数", "再生時間"]


# 結果欄のフォント候補（先頭から順に、存在するものを使う）
# Consolas 等の日本語非対応フォントだと、日本語が合成フォントで太字っぽく表示される。
# Windows 標準の日本語フォントを優先する。
FONT_CANDIDATES = [
    "Meiryo UI",        # Windows 標準（日本語対応）
    "Yu Gothic UI",     # Windows 8.1 以降の標準
    "ＭＳ ゴシック",     # 標準の等幅フォント（TSVの桁が揃う）
    "MS UI Gothic",
    "Meiryo",
    "Noto Sans JP",
]


def script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def pick_text_font(root, size=10):
    """日本語を正しく表示できる等幅寄りのフォントを選ぶ。"""
    available = set(tkfont.families(root))
    for name in FONT_CANDIDATES:
        if name in available:
            return (name, size)
    return tkfont.nametofont("TkFixedFont")


# ---------------------------------------------------------------------------
# cookie.txt の読み込み
# ---------------------------------------------------------------------------
def cookie_file_path():
    """保存先（`nicoids.py` と同じフォルダの `cookie.txt`）。"""
    return os.path.join(script_dir(), "cookie.txt")


def cookie_file_candidates():
    """cookie.txt の読み取り候補。

    保存・削除・有無確認と同じ **`nicoids.py` と同じフォルダだけ**を見る
    （カレントディレクトリは見ない）。読み書きの対象を1箇所に揃えるため。
    """
    return [cookie_file_path()]


def extract_user_session(text):
    """cookie.txt の中身から user_session の値を取り出す（複数形式に対応）。

    対応する内容の例:
      - user_session_83033_xxxxx                （値のみ）
      - user_session=user_session_83033_xxxxx   （name=value）
      - Netscape 形式（タブ区切り）
      - ブラウザの Cookie ヘッダ文字列
    """
    if not text:
        return None

    # name=value 形式
    m = re.search(r"(?:^|[;\s\t])user_session\s*=\s*([^\s;]+)", text)
    if m:
        return m.group(1).strip().strip('"')

    # Netscape 形式（タブ区切り）: ...\tuser_session\t<value>
    for line in text.splitlines():
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
            if "user_session" in parts:
                idx = parts.index("user_session")
                if idx + 1 < len(parts) and parts[idx + 1]:
                    return parts[idx + 1].strip('"')

    # 値のみ（user_session_<id>_<token>）
    m = re.search(r"(user_session_[A-Za-z0-9_\-]+)", text)
    if m:
        return m.group(1).strip('"')

    # 最後の手段: 1 行だけならそのまま値として扱う
    stripped = text.strip().strip('"')
    if stripped and "\n" not in stripped:
        return stripped
    return None


_USER_SESSION_VALUE_RE = re.compile(r"^user_session_\d+_[A-Za-z0-9_\-]+$")


def is_user_session_value(value):
    """user_session_<数字>_<トークン> 形式かどうか。

    GUI から貼り付けた値の検証用。`extract_user_session` の「1行ならそのまま」
    フォールバックが緩いので、ダイアログ経路ではここで形式を確認する。
    """
    return bool(value) and bool(_USER_SESSION_VALUE_RE.match(value))


def load_user_session(paths=None):
    """cookie.txt から user_session を読み取る。

    戻り値: (value, path)
      - 見つかった         : (値, パス)
      - あるが値が無い     : (None, パス)
      - ファイルが無い     : (None, None)

    複数の候補を順に試し、値が取れた最初のファイルを使う。
    paths を渡すと検索先を差し替えられる（テスト用）。
    """
    first_found = None
    for path in (cookie_file_candidates() if paths is None else paths):
        if not os.path.isfile(path):
            continue
        if first_found is None:
            first_found = path
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="cp932", errors="replace") as f:
                text = f.read()
        except OSError:
            # 権限エラー等。起動を止めないよう、この候補は飛ばす。
            continue
        value = extract_user_session(text)
        if value:
            return value, path
    return None, first_found


def has_saved_session(path=None):
    """保存済みの cookie.txt があるか。"""
    return os.path.isfile(path or cookie_file_path())


def save_user_session(value, path=None):
    """`user_session` を cookie.txt に保存する（平文・値のみ1行）。

    保存先は `nicoids.py` と同じフォルダに固定（任意パスは受け付けない）。
    書き込みは一時ファイル経由で行い、途中で失敗しても既存の内容を壊さない。
    """
    path = path or cookie_file_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(value + "\n")
    os.replace(tmp, path)
    return path


def delete_saved_session(path=None):
    """保存済みの cookie.txt を削除する。戻り値: 削除したら True。"""
    path = path or cookie_file_path()
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    return True


def resolve_session():
    """マイリスト取得に使う user_session を cookie.txt から決める。

    戻り値: (value, source)
      source: "cookie"         … cookie.txt の値を使う
              "invalid_cookie" … cookie.txt はあるが user_session を読み取れない
              None             … cookie.txt が無い
    """
    value, path = load_user_session()
    if value:
        return value, "cookie"
    if path:
        return None, "invalid_cookie"
    return None, None


# ---------------------------------------------------------------------------
# HTTP / API
# ---------------------------------------------------------------------------
def http_get_json(url, cookie=None):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-Frontend-ID": "6",
        "X-Frontend-Version": "0",
    }
    if cookie:
        headers["Cookie"] = cookie

    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last_error = e
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise
    raise last_error


def http_get_text(url, cookie=None):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ja,en-US;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie

    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last_error = e
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise
    raise last_error


_SERVER_RESPONSE_RE = re.compile(
    r'<meta\s+name="server-response"\s+content="([\s\S]*?)"\s*/?>'
)


def extract_embedded_json(page_html):
    """検索ページに埋め込まれた server-response の JSON を取り出す。"""
    m = _SERVER_RESPONSE_RE.search(page_html)
    if not m:
        return None
    try:
        return json.loads(html.unescape(m.group(1)))
    except ValueError:
        return None


def normalize_search_url(url):
    """非ASCIIや半角スペースをエンコードする（既存の %xx / + / - は保持）。"""
    out = []
    for ch in (url or "").strip():
        code = ord(ch)
        if code > 127:
            out.append(urllib.parse.quote(ch))
        elif ch == " ":
            out.append("+")
        else:
            out.append(ch)
    return "".join(out)


def set_query_param(url, key, value):
    """URL にクエリパラメータを付与（既に存在すれば置換）。"""
    pattern = re.compile(r"([?&]" + re.escape(key) + r")=[^&]*")
    if pattern.search(url):
        return pattern.sub(lambda m: f"{m.group(1)}={value}", url)
    sep = "&" if ("?" in url) else "?"
    return f"{url}{sep}{key}={value}"


def _video_info_from_item(item):
    """シリーズ/マイリストの1件から動画情報を取り出す（無ければ None）。"""
    if not isinstance(item, dict):
        return None

    video = item.get("video")
    if not isinstance(video, dict):
        video = item

    vid = video.get("id")
    if not vid:
        meta = item.get("meta")
        if isinstance(meta, dict) and meta.get("id"):
            vid = meta["id"]
    if not vid:
        return None

    count = video.get("count") or {}
    owner = video.get("owner") or {}
    return {
        "id": vid,
        "title": video.get("title") or "",
        "view": count.get("view"),
        "comment": count.get("comment"),
        "duration": video.get("duration"),
        "owner": owner.get("name") or "",
        "registered_at": video.get("registeredAt") or "",
        "description": video.get("shortDescription") or "",
    }


def _stop_requested(should_stop):
    return bool(should_stop and should_stop())


def _limit_reached(videos, max_items):
    return max_items is not None and len(videos) >= max_items


def _trim(videos, max_items):
    if max_items is not None and len(videos) > max_items:
        return videos[:max_items]
    return videos


def fetch_series(series_id, progress=None, should_stop=None, max_items=None):
    videos = []
    page = 1
    total = None
    reason = None
    while True:
        url = (
            f"{API_BASE}/v2/series/{series_id}"
            f"?pageSize={PAGE_SIZE}&page={page}&sensitiveContents=mask"
        )
        data = http_get_json(url).get("data") or {}
        if total is None:
            total = data.get("totalCount")
        items = data.get("items") or []
        if progress:
            progress(f"シリーズを取得中… page {page}（{len(videos)}件）")
        for item in items:
            info = _video_info_from_item(item)
            if info:
                videos.append(info)
        if _limit_reached(videos, max_items):
            reason = "max_items"
            break
        if _stop_requested(should_stop):
            reason = "cancelled"
            break
        if not items or len(items) < PAGE_SIZE:
            break
        if total is not None and len(videos) >= total:
            break
        page += 1
        time.sleep(0.2)
    return _trim(videos, max_items), total, reason


def fetch_mylist(mylist_id, session, progress=None, should_stop=None, max_items=None):
    cookie = "user_session=" + session
    videos = []
    page = 1
    total = None
    reason = None
    while True:
        url = f"{API_BASE}/v2/mylists/{mylist_id}?pageSize={PAGE_SIZE}&page={page}"
        data = http_get_json(url, cookie=cookie).get("data") or {}
        mylist = data.get("mylist") or {}
        if total is None:
            total = mylist.get("totalItemCount")
        items = mylist.get("items") or []
        has_next = mylist.get("hasNext")
        if progress:
            progress(f"マイリストを取得中… page {page}（{len(videos)}件）")
        for item in items:
            info = _video_info_from_item(item)
            if info:
                videos.append(info)
        if _limit_reached(videos, max_items):
            reason = "max_items"
            break
        if _stop_requested(should_stop):
            reason = "cancelled"
            break
        if not items:
            break
        if has_next is False:
            break
        if total is not None and len(videos) >= total:
            break
        if len(items) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.2)
    return _trim(videos, max_items), total, reason


# ---------------------------------------------------------------------------
# 検索結果（/tag/… ・ /search/…）
# ---------------------------------------------------------------------------
def fetch_search(page_url, progress=None, should_stop=None, max_items=None):
    """タグ検索 / キーワード検索の結果を取得する。

    戻り値: (videos, total, reason)
      reason: None(全部取得) / "page_limit" / "max_items" / "cancelled"
    """
    base = normalize_search_url(page_url)
    videos = []
    page = 1
    total = None
    reason = None

    while True:
        url = set_query_param(base, "page", page)
        payload = extract_embedded_json(http_get_text(url))
        response = (payload or {}).get("data", {}).get("response", {})
        node = response.get("$getSearchVideoV2") if isinstance(response, dict) else None
        if not isinstance(node, dict):
            raise RuntimeError(
                "検索結果を読み取れませんでした（ページ構造が想定と異なります）。"
            )

        if "error" in node:
            err = node.get("error") or {}
            heading = err.get("heading") or ""
            if "ページ" in heading:
                reason = "page_limit"
                break
            raise RuntimeError(f"検索エラー: {heading or err.get('message') or err}")

        data = node.get("data") or {}
        if total is None:
            total = data.get("totalCount")
        items = data.get("items") or []
        if progress:
            progress(f"検索結果を取得中… page {page}（{len(videos)}件）")
        for item in items:
            info = _video_info_from_item(item)
            if info:
                videos.append(info)

        if _limit_reached(videos, max_items):
            reason = "max_items"
            break
        if _stop_requested(should_stop):
            reason = "cancelled"
            break
        if not items or not data.get("hasNext"):
            break
        page += 1
        if page > SEARCH_MAX_PAGE + 2:
            reason = "page_limit"
            break
        time.sleep(0.3)

    if reason is None and total is not None and len(videos) < total:
        reason = "page_limit"
    return _trim(videos, max_items), total, reason


# ---------------------------------------------------------------------------
# 入力解析・整形
# ---------------------------------------------------------------------------
def parse_target(text, force_type=TYPE_AUTO):
    t = (text or "").strip()
    if not t:
        return None

    # 検索結果URL（/tag/… ・ /search/…）はURL全体を使う
    if force_type == TYPE_AUTO and re.search(r"/(?:tag|search)/", t):
        url = t
        if not re.match(r"^https?://", url):
            url = "https://www.nicovideo.jp/" + url.lstrip("/")
        return KIND_SEARCH, url

    kind = None
    ident = None
    m = re.search(r"/series/(\d+)", t)
    if m:
        kind, ident = KIND_SERIES, m.group(1)
    else:
        m = re.search(r"/mylist/(?:#/)?(\d+)", t)
        if m:
            kind, ident = KIND_MYLIST, m.group(1)

    if ident is None:
        m = re.search(r"(\d+)", t)
        if not m:
            return None
        ident = m.group(1)
        kind = KIND_SERIES  # 数字だけのときはシリーズ扱い

    if force_type == TYPE_SERIES:
        kind = KIND_SERIES
    elif force_type == TYPE_MYLIST:
        kind = KIND_MYLIST

    return kind, ident


def strip_prefix(video_id):
    return re.sub(r"^[A-Za-z]+", "", video_id)


def sanitize_cell(text):
    """TSV を壊さないよう、タブ・改行・連続空白を1つの半角スペースに整える。"""
    return re.sub(r"\s+", " ", str(text if text is not None else "")).strip()


def format_duration(seconds):
    """秒を mm:ss（1時間以上は h:mm:ss）形式にする。"""
    if seconds is None or seconds == "":
        return ""
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if s < 0:
        s = 0
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def format_count(value):
    if value is None or value == "":
        return ""
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class LoginDialog(tk.Toplevel):
    """マイリスト用の user_session を cookie.txt に保存／削除するモーダルダイアログ。

    - 貼り付けた文字列は extract_user_session() で正規化し、
      is_user_session_value() で user_session_<数字>_<トークン> 形式かを検証する
      （値のみ / user_session=… / Cookie ヘッダ全体、いずれでも可。形式違いは警告して閉じない）。
    - 「保存する」で nicoids.py と同じフォルダの cookie.txt に平文で保存する。
    - 確定後に self.action（"save" / "delete" / None）と self.value を見る。
    """

    def __init__(self, master, saved_path=None, saved_exists=False):
        super().__init__(master)
        self.title("ログイン設定")
        self.action = None      # "save" / "delete" / None（キャンセル）
        self.value = None       # action == "save" のときの正規化済み user_session
        self._saved_exists = saved_exists

        body = ttk.Frame(self, padding=(12, 12, 12, 0))
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, justify="left",
            text=("マイリストの取得に使う user_session を入力します。\n"
                  "ブラウザで F12 → Application → Cookies から user_session の値を\n"
                  "コピーして貼り付けてください。\n"
                  "「値のみ」「user_session=…」「Cookieヘッダ全体」のどれでもかまいません。"),
        ).pack(anchor="w")

        row = ttk.Frame(body, padding=(0, 8, 0, 0))
        row.pack(fill="x")
        self.value_var = tk.StringVar(value="")
        # user_session は 80〜90 文字程度になるため、横幅に余裕を持たせる
        self.entry = ttk.Entry(row, textvariable=self.value_var, width=96, show="●")
        self.entry.pack(side="left", fill="x", expand=True)
        # 「クリア」は入力欄の内容だけを消す（保存済みファイルには触らない）
        ttk.Button(row, text="クリア", command=self._on_clear).pack(side="left", padx=(6, 0))

        self.show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body, text="値を表示する", variable=self.show_var, command=self._toggle_show,
        ).pack(anchor="w", pady=(4, 0))

        note = ("「保存する」と、nicoids.py と同じフォルダの cookie.txt に\n"
                "平文で書き込まれます。")
        if saved_path:
            note += f"\n保存先: {saved_path}"
        if saved_exists:
            note += "\n保存済みの cookie.txt があります（消すときは「ログイン情報を削除する」）。"
        ttk.Label(
            body, justify="left", foreground="#666666", text=note,
        ).pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(self, padding=(12, 10, 12, 12))
        btns.pack(fill="x")
        self.delete_btn = ttk.Button(
            btns, text="ログイン情報を削除する", command=self._on_delete,
        )
        self.delete_btn.pack(side="left")
        ttk.Button(btns, text="キャンセル", command=self._on_cancel).pack(side="right")
        ttk.Button(btns, text="保存する", command=self._on_save).pack(side="right", padx=(0, 6))

        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # 内容が収まるサイズを最小値にして、長い値のときは広げられるようにする
        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        self.resizable(True, True)

        self.transient(master)
        self.grab_set()
        self.entry.focus_set()

    def _toggle_show(self):
        self.entry.configure(show="" if self.show_var.get() else "●")

    def _on_save(self):
        raw = self.value_var.get().strip()
        if not raw:
            messagebox.showwarning(
                "入力エラー",
                "user_session を入力してください。",
                parent=self,
            )
            return
        value = extract_user_session(raw)
        if not is_user_session_value(value):
            messagebox.showwarning(
                "読み取れません",
                "貼り付けた文字列から user_session を読み取れませんでした。\n"
                "「user_session_…」で始まる値か、Cookie の行をコピーし直してください。",
                parent=self,
            )
            return
        self.action = "save"
        self.value = value
        self.destroy()

    def _on_clear(self):
        # 入力欄を空にするだけ（保存済みファイルは消さない）
        self.value_var.set("")

    def _on_delete(self):
        if self._saved_exists and not messagebox.askyesno(
            "ログイン情報を削除",
            "保存したログイン情報（cookie.txt）を削除します。\nよろしいですか？",
            parent=self,
        ):
            return
        self.action = "delete"
        self.value = None
        self.destroy()

    def _on_cancel(self):
        self.action = None
        self.value = None
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"ニコニコ動画 ID エクスポート v{__version__}")
        self.geometry("660x520")
        self.minsize(620, 420)   # 「ログイン設定…」＋状態ラベルを右端に置くため余裕を持たせる

        self._busy = False
        self._videos = []
        self._cancel = threading.Event()
        self._login_dlg = None        # ログイン設定ダイアログ（多重生成防止）
        self._relogin_needed = False  # 403 を受けて再ログイン待ちかどうか

        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.pack(side="top", fill="x")

        ttk.Label(top, text="URL:").pack(side="left")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.url_entry.bind("<Return>", lambda e: self.on_fetch())
        self.fetch_btn = ttk.Button(top, text="取得", command=self.on_fetch)
        self.fetch_btn.pack(side="left")
        self.abort_btn = ttk.Button(top, text="中断", command=self.on_abort, state="disabled")
        self.abort_btn.pack(side="left", padx=(6, 0))

        opts = ttk.Frame(self, padding=(10, 6, 10, 0))
        opts.pack(side="top", fill="x")
        ttk.Label(opts, text="種類:").pack(side="left")
        self.type_var = tk.StringVar(value=TYPE_AUTO)
        self.type_box = ttk.Combobox(
            opts, textvariable=self.type_var, state="readonly", width=10,
            values=[TYPE_AUTO, TYPE_SERIES, TYPE_MYLIST],
        )
        self.type_box.pack(side="left", padx=(6, 16))
        self.numeric_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="数値のみ (so/sm を外す)", variable=self.numeric_var,
            command=self.render,
        ).pack(side="left")
        self.login_state_var = tk.StringVar(value="ログイン: 未設定")
        ttk.Label(opts, textvariable=self.login_state_var).pack(side="right", padx=(6, 0))
        self.login_btn = ttk.Button(
            opts, text="ログイン設定…", command=self.open_login_dialog,
        )
        self.login_btn.pack(side="right")

        opts2 = ttk.Frame(self, padding=(10, 4, 10, 0))
        opts2.pack(side="top", fill="x")
        ttk.Label(opts2, text="出力形式:").pack(side="left")
        self.mode_var = tk.StringVar(value=MODE_TSV)
        ttk.Radiobutton(
            opts2, text=MODE_TSV, value=MODE_TSV, variable=self.mode_var,
            command=self.render,
        ).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(
            opts2, text=MODE_ID, value=MODE_ID, variable=self.mode_var,
            command=self.render,
        ).pack(side="left", padx=(6, 16))
        self.header_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts2, text="ヘッダ行を付ける", variable=self.header_var,
            command=self.render,
        ).pack(side="left")

        opts3 = ttk.Frame(self, padding=(10, 4, 10, 0))
        opts3.pack(side="top", fill="x")
        ttk.Label(opts3, text="最大件数:").pack(side="left")
        self.max_var = tk.StringVar(value="")
        self.max_entry = ttk.Entry(opts3, textvariable=self.max_var, width=8)
        self.max_entry.pack(side="left", padx=(6, 2))
        ttk.Label(opts3, text="件").pack(side="left")
        ttk.Label(
            opts3, text="（空欄＝制限なし／検索は約5,000件が上限）",
        ).pack(side="left", padx=(8, 0))

        mid = ttk.Frame(self, padding=(10, 8, 10, 0))
        self.text = tk.Text(mid, wrap="none", undo=False, height=12, font=pick_text_font(self, 10))
        scroll = ttk.Scrollbar(mid, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        bottom = ttk.Frame(self, padding=(10, 8, 10, 10))
        bottom.pack(side="bottom", fill="x")
        self.copy_btn = ttk.Button(bottom, text="コピー", command=self.on_copy)
        self.copy_btn.pack(side="left")
        self.save_btn = ttk.Button(bottom, text="ファイルに保存", command=self.on_save)
        self.save_btn.pack(side="left", padx=(6, 0))

        self.status_var = tk.StringVar(value="URL を入力して「取得」を押してください。")
        ttk.Label(
            self, textvariable=self.status_var, anchor="w", padding=(10, 0, 10, 8),
        ).pack(side="bottom", fill="x")

        # 最後に中央の結果欄を配置して、余った領域を吸収させる
        mid.pack(side="top", fill="both", expand=True)

        self.update_login_indicator()

    # -- helpers ----------------------------------------------------------
    def build_lines(self):
        numeric = self.numeric_var.get()
        mode = self.mode_var.get()

        def ident(video):
            return strip_prefix(video["id"]) if numeric else video["id"]

        if mode == MODE_ID:
            return [ident(v) for v in self._videos]

        lines = []
        if self.header_var.get():
            lines.append("\t".join(TSV_HEADER))
        for v in self._videos:
            lines.append("\t".join([
                ident(v),
                sanitize_cell(v["title"]),
                format_count(v["view"]),
                format_count(v["comment"]),
                format_duration(v["duration"]),
            ]))
        return lines

    def render(self):
        lines = self.build_lines()
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(lines))

    def get_results(self):
        return [ln for ln in self.text.get("1.0", "end").splitlines() if ln.strip()]

    def set_status(self, msg):
        self.status_var.set(msg)

    def update_login_indicator(self, resolved=None):
        """ログイン状態ラベルを、cookie.txt の状態に合わせる。

        resolved に (value, source) を渡すと、その結果を使って再解決を省く。
        """
        if self._relogin_needed:
            self.login_state_var.set("ログイン: 要再ログイン")
            return
        value, source = resolve_session() if resolved is None else resolved
        if value:
            label = "設定済み（cookie.txt）"
        elif source == "invalid_cookie":
            label = "cookie.txt を読み取れません"
        else:
            label = "未設定"
        self.login_state_var.set("ログイン: " + label)

    def open_login_dialog(self):
        """ログイン設定ダイアログを開く（多重生成しない）。"""
        if self._login_dlg is not None and self._login_dlg.winfo_exists():
            self._login_dlg.lift()
            self._login_dlg.focus_set()
            return
        saved_path = cookie_file_path()
        dlg = LoginDialog(
            self, saved_path=saved_path, saved_exists=has_saved_session(saved_path),
        )
        self._login_dlg = dlg
        self.wait_window(dlg)
        self._login_dlg = None

        if dlg.action == "save":
            self._save_session(dlg.value)
        elif dlg.action == "delete":
            self._delete_saved_session()

    def _save_session(self, value):
        try:
            path = save_user_session(value)
        except OSError as e:
            messagebox.showerror(
                "保存できません", f"cookie.txt に保存できませんでした:\n{e}",
            )
            return
        # 保存できた＝新しい値なので、再ログイン待ちを解除する
        self._relogin_needed = False
        self.update_login_indicator()
        self.set_status(f"ログイン情報を保存しました（{os.path.basename(path)}）。")

    def _delete_saved_session(self):
        try:
            removed = delete_saved_session()
        except OSError as e:
            messagebox.showerror(
                "削除できません", f"cookie.txt を削除できませんでした:\n{e}",
            )
            return
        # 消したのに「要再ログイン」のままだと矛盾するので解除する
        self._relogin_needed = False
        self.update_login_indicator()
        self.set_status(
            "ログイン情報を削除しました（cookie.txt）。" if removed
            else "保存されたログイン情報はありません。"
        )

    def set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.fetch_btn.configure(state=state)
        self.copy_btn.configure(state=state)
        self.save_btn.configure(state=state)
        self.url_entry.configure(state=state)
        self.max_entry.configure(state=state)
        self.login_btn.configure(state=state)
        self.abort_btn.configure(state=("normal" if busy else "disabled"))

    def get_max_items(self):
        raw = self.max_var.get().strip()
        if not raw:
            return None
        try:
            value = int(raw.replace(",", ""))
        except ValueError:
            return None
        return value if value > 0 else None

    # -- actions ----------------------------------------------------------
    def on_fetch(self):
        if self._busy:
            return
        target = parse_target(self.url_var.get(), self.type_var.get())
        if not target:
            messagebox.showwarning("入力エラー", "URL または ID を入力してください。")
            return
        kind, ident = target

        # マイリストは認証が要る。スレッドを起こす前に user_session を解決する。
        session = None
        if kind == KIND_MYLIST:
            session = self._ensure_session()
            if session is None:
                return

        self._cancel.clear()
        self.set_busy(True)
        self.set_status("取得中…")
        self._videos = []
        self.render()
        threading.Thread(
            target=self._worker, args=(kind, ident, self.get_max_items(), session),
            daemon=True,
        ).start()

    def _ensure_session(self):
        """マイリスト用の user_session を用意する。無ければ設定ダイアログへ誘導し None を返す。"""
        session, source = resolve_session()
        self.update_login_indicator((session, source))
        if session:
            return session

        if source == "invalid_cookie":
            msg = ("cookie.txt から user_session を読み取れませんでした。\n"
                   "「ログイン設定…」で user_session を保存し直してください。")
        else:
            msg = ("マイリストの取得にはログイン設定が必要です。\n"
                   "「ログイン設定…」から user_session を保存してください。")
        self.set_status("ログイン設定が必要です。")
        if not messagebox.askyesno("ログイン設定が必要です", msg + "\n\n今すぐ設定を開きますか？"):
            return None

        self.open_login_dialog()
        session, _ = resolve_session()
        return session or None

    def on_abort(self):
        if not self._busy:
            return
        self._cancel.set()
        self.set_status("中断しています…（ここまでの結果を表示します）")

    def _worker(self, kind, ident, max_items, session=None):
        try:
            if kind == KIND_SERIES:
                videos, total, reason = fetch_series(
                    ident, progress=self._progress,
                    should_stop=self._cancel.is_set, max_items=max_items,
                )
            elif kind == KIND_SEARCH:
                videos, total, reason = fetch_search(
                    ident, progress=self._progress,
                    should_stop=self._cancel.is_set, max_items=max_items,
                )
            else:
                if not session:
                    raise RuntimeError(
                        "マイリストの取得にはログイン設定が必要です。\n"
                        "「ログイン設定…」から user_session を保存してください。"
                    )
                videos, total, reason = fetch_mylist(
                    ident, session, progress=self._progress,
                    should_stop=self._cancel.is_set, max_items=max_items,
                )
        except urllib.error.HTTPError as e:
            if e.code == 403 and kind == KIND_MYLIST:
                self.after(0, self._mark_relogin)
                msg = ("ログイン情報（user_session）が無効、または期限切れです（403）。\n"
                       "ブラウザでログインし直し、「ログイン設定…」で保存し直してください。")
            elif e.code == 404:
                label = "シリーズ" if kind == KIND_SERIES else "マイリスト"
                msg = f"{label}が見つかりません（404）。"
            else:
                msg = f"HTTP エラー {e.code}: {e.reason}"
            self._fail(msg)
            return
        except Exception as e:  # noqa: BLE001
            self._fail(f"エラー: {e}")
            return
        self.after(0, self._success, kind, videos, total, reason)

    def _mark_relogin(self):
        self._relogin_needed = True
        self.update_login_indicator()

    def _progress(self, msg):
        self.after(0, self.set_status, msg)

    def _success(self, kind, videos, total=None, reason=None):
        self._videos = videos
        self.render()
        self.set_busy(False)
        if kind == KIND_MYLIST:
            # マイリストの取得成功＝今のログイン情報は有効なので、再ログイン待ちを解除する
            self._relogin_needed = False
            self.update_login_indicator()
        count = len(videos)
        if reason == "cancelled":
            self.set_status(f"中断しました（{count}件）。")
        elif reason == "max_items":
            self.set_status(f"{count}件取得しました（指定した最大件数に達したため終了）。")
        elif reason == "page_limit" and total is not None:
            self.set_status(
                f"{count}件取得しました（全{total}件。検索の上限等のため途中で打ち切り）。"
            )
            messagebox.showwarning(
                "一部のみ取得",
                f"全{total}件のうち {count}件のみ取得しました。\n"
                "ニコニコの検索結果は約5,000件が上限のため、それ以降は取得できません。\n"
                "「最大件数」を指定すると、より早く切り上げられます。",
            )
        else:
            self.set_status(f"{count}件取得しました。")

    def _fail(self, msg):
        self.after(0, self.set_busy, False)
        self.after(0, self.set_status, msg.splitlines()[0])
        self.after(0, messagebox.showerror, "取得失敗", msg)

    def on_copy(self):
        lines = self.get_results()
        if not lines:
            self.set_status("コピーする内容がありません。")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.set_status(f"{len(self._videos)}件をクリップボードにコピーしました。")

    def on_save(self):
        lines = self.get_results()
        if not lines:
            self.set_status("保存する内容がありません。")
            return
        is_tsv = self.mode_var.get() == MODE_TSV
        path = filedialog.asksaveasfilename(
            title="保存先を選択",
            defaultextension=".tsv" if is_tsv else ".txt",
            initialfile="nicovideo.tsv" if is_tsv else "ids.txt",
            filetypes=(
                [("TSVファイル", "*.tsv"), ("テキストファイル", "*.txt"), ("すべてのファイル", "*.*")]
                if is_tsv else
                [("テキストファイル", "*.txt"), ("すべてのファイル", "*.*")]
            ),
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        self.set_status(f"{len(self._videos)}件を保存しました: {path}")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
