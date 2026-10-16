# -*- coding: utf-8 -*-
"""ニコニコ動画のシリーズ / マイリストから動画情報を書き出す GUI ツール。

- シリーズ: 認証不要（nvapi v2/series）
- マイリスト: 同フォルダの cookie.txt から user_session を読み取って使用（nvapi v2/mylists）

出力モード:
- TSV（詳細）: 動画ID / タイトル / 再生数 / コメント数 / 再生時間(mm:ss)
- IDのみ    : 動画IDを改行区切りで出力

標準ライブラリのみで動作します（tkinter / urllib）。
"""

import json
import os
import re
import threading
import time
import urllib.error
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
def cookie_file_candidates():
    name = "cookie.txt"
    return [
        os.path.join(script_dir(), name),
        os.path.join(os.getcwd(), name),
    ]


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


def load_user_session():
    for path in cookie_file_candidates():
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    text = f.read()
            except UnicodeDecodeError:
                with open(path, "r", encoding="cp932", errors="replace") as f:
                    text = f.read()
            value = extract_user_session(text)
            if value:
                return value, path
            return None, path
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


def fetch_series(series_id, progress=None):
    videos = []
    page = 1
    total = None
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
        if not items or len(items) < PAGE_SIZE:
            break
        if total is not None and len(videos) >= total:
            break
        page += 1
        time.sleep(0.2)
    return videos, total


def fetch_mylist(mylist_id, session, progress=None):
    cookie = "user_session=" + session
    videos = []
    page = 1
    total = None
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
    return videos, total


# ---------------------------------------------------------------------------
# 入力解析・整形
# ---------------------------------------------------------------------------
def parse_target(text, force_type=TYPE_AUTO):
    t = (text or "").strip()
    if not t:
        return None

    kind = None
    ident = None
    m = re.search(r"/series/(\d+)", t)
    if m:
        kind, ident = "series", m.group(1)
    else:
        m = re.search(r"/mylist/(?:#/)?(\d+)", t)
        if m:
            kind, ident = "mylist", m.group(1)

    if ident is None:
        m = re.search(r"(\d+)", t)
        if not m:
            return None
        ident = m.group(1)
        kind = "series"  # 数字だけのときはシリーズ扱い

    if force_type == TYPE_SERIES:
        kind = "series"
    elif force_type == TYPE_MYLIST:
        kind = "mylist"

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
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ニコニコ動画 ID エクスポート")
        self.geometry("660x520")
        self.minsize(560, 420)

        self._busy = False
        self._videos = []

        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.pack(side="top", fill="x")

        ttk.Label(top, text="URL:").pack(side="left")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.url_entry.bind("<Return>", lambda e: self.on_fetch())
        self.fetch_btn = ttk.Button(top, text="取得", command=self.on_fetch)
        self.fetch_btn.pack(side="left")

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

    def set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.fetch_btn.configure(state=state)
        self.copy_btn.configure(state=state)
        self.save_btn.configure(state=state)
        self.url_entry.configure(state=state)

    # -- actions ----------------------------------------------------------
    def on_fetch(self):
        if self._busy:
            return
        target = parse_target(self.url_var.get(), self.type_var.get())
        if not target:
            messagebox.showwarning("入力エラー", "URL または ID を入力してください。")
            return
        kind, ident = target
        self.set_busy(True)
        self.set_status("取得中…")
        self._videos = []
        self.render()
        threading.Thread(
            target=self._worker, args=(kind, ident), daemon=True,
        ).start()

    def _worker(self, kind, ident):
        try:
            if kind == "series":
                videos, total = fetch_series(ident, progress=self._progress)
            else:
                session, path = load_user_session()
                if not session:
                    if path:
                        raise RuntimeError(
                            f"cookie.txt から user_session を読み取れませんでした:\n{path}"
                        )
                    raise RuntimeError(
                        "マイリストの取得には cookie.txt が必要です。\n"
                        f"{os.path.join(script_dir(), 'cookie.txt')} に user_session の値を保存してください。"
                    )
                videos, total = fetch_mylist(ident, session, progress=self._progress)
        except urllib.error.HTTPError as e:
            if e.code == 403 and kind == "mylist":
                msg = ("cookie.txt の user_session が無効、または期限切れです（403）。\n"
                       "ブラウザでログインし直し、cookie.txt を更新してください。")
            elif e.code == 404:
                msg = f"{'シリーズ' if kind == 'series' else 'マイリスト'}が見つかりません（404）。"
            else:
                msg = f"HTTP エラー {e.code}: {e.reason}"
            self._fail(msg)
            return
        except Exception as e:  # noqa: BLE001
            self._fail(f"エラー: {e}")
            return
        self.after(0, self._success, videos)

    def _progress(self, msg):
        self.after(0, self.set_status, msg)

    def _success(self, videos):
        self._videos = videos
        self.render()
        self.set_busy(False)
        self.set_status(f"{len(videos)}件取得しました。")

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
