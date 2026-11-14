# -*- coding: utf-8 -*-
"""nicoids.py の単体テスト。

- ネットワークは一切叩かない（HTTP は `urlopen` をモックして確認し、実通信はしない）。
- 実トークンは使わない。すべてダミー値。
- 確認コマンドやログに実セッション値を出さないこと（AGENTS.md 参照）。

実行（リポジトリ直下で）:
    python -m unittest discover -s tests
"""

import os
import tempfile
import unittest
import urllib.error
from unittest import mock

import nicoids as n


# ---------------------------------------------------------------------------
# extract_user_session / is_user_session_value
# ---------------------------------------------------------------------------
class ExtractUserSessionTest(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(n.extract_user_session(""))
        self.assertIsNone(n.extract_user_session("   "))
        self.assertIsNone(n.extract_user_session(None))

    def test_value_only(self):
        self.assertEqual(
            n.extract_user_session("user_session_83033_abcDEF"),
            "user_session_83033_abcDEF",
        )

    def test_name_value(self):
        self.assertEqual(
            n.extract_user_session("user_session=user_session_83033_abc"),
            "user_session_83033_abc",
        )

    def test_name_value_with_spaces(self):
        self.assertEqual(
            n.extract_user_session("user_session = user_session_83033_abc"),
            "user_session_83033_abc",
        )

    def test_cookie_header(self):
        self.assertEqual(
            n.extract_user_session("os=1; user_session=user_session_1_ab; x=2"),
            "user_session_1_ab",
        )

    def test_netscape(self):
        line = "www.nicovideo.jp\tFALSE\t/\tTRUE\t0\tuser_session\tuser_session_1_ab"
        self.assertEqual(n.extract_user_session(line), "user_session_1_ab")

    def test_quoted(self):
        self.assertEqual(
            n.extract_user_session('user_session="user_session_1_ab"'),
            "user_session_1_ab",
        )

    def test_single_line_fallback(self):
        # cookie.txt 用の緩いフォールバック（ダイアログ側は is_user_session_value で弾く）
        self.assertEqual(n.extract_user_session("some_random_value"), "some_random_value")

    def test_multiline_without_match(self):
        self.assertIsNone(n.extract_user_session("foo\nbar\nbaz"))


class IsUserSessionValueTest(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(n.is_user_session_value("user_session_83033_abcDEF123"))
        self.assertTrue(n.is_user_session_value("user_session_1_ab-cd_ef"))

    def test_invalid(self):
        self.assertFalse(n.is_user_session_value("https://example.com/whatever"))
        self.assertFalse(n.is_user_session_value("a=1; b=2"))
        self.assertFalse(n.is_user_session_value("user_session_abc"))
        self.assertFalse(n.is_user_session_value(""))
        self.assertFalse(n.is_user_session_value(None))


# ---------------------------------------------------------------------------
# load_user_session / resolve_session
# ---------------------------------------------------------------------------
class LoadUserSessionTest(unittest.TestCase):
    def _write(self, directory, name, text):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_reads_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "cookie.txt", "user_session_1_abc\n")
            self.assertEqual(n.load_user_session(paths=[path]), ("user_session_1_abc", path))

    def test_file_without_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "cookie.txt", "hello\nworld\n")
            self.assertEqual(n.load_user_session(paths=[path]), (None, path))

    def test_missing_file(self):
        missing = os.path.join(tempfile.gettempdir(), "no_such_cookie_9f3a.txt")
        self.assertEqual(n.load_user_session(paths=[missing]), (None, None))

    def test_directory_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(n.load_user_session(paths=[d]), (None, None))

    def test_first_candidate_wins(self):
        with tempfile.TemporaryDirectory() as d:
            good = self._write(d, "b.txt", "user_session_1_abc\n")
            missing = os.path.join(d, "a.txt")
            self.assertEqual(n.load_user_session(paths=[missing, good]),
                             ("user_session_1_abc", good))

    def test_skips_file_without_value_to_find_later(self):
        # 値が無いファイルで打ち切らず、後続の候補も試す
        with tempfile.TemporaryDirectory() as d:
            empty = self._write(d, "a.txt", "")           # 空ファイル＝値なし
            good = self._write(d, "b.txt", "user_session_1_abc\n")
            self.assertEqual(n.load_user_session(paths=[empty, good]),
                             ("user_session_1_abc", good))

    def test_unreadable_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "cookie.txt", "user_session_1_abc\n")
            with mock.patch("builtins.open", side_effect=PermissionError("denied")):
                self.assertEqual(n.load_user_session(paths=[path]), (None, path))


class SavedSessionTest(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cookie.txt")
            n.save_user_session("user_session_1_abc", path=path)
            self.assertTrue(n.has_saved_session(path))
            self.assertEqual(n.load_user_session(paths=[path]), ("user_session_1_abc", path))

    def test_saved_file_is_value_only_single_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cookie.txt")
            n.save_user_session("user_session_1_abc", path=path)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "user_session_1_abc\n")

    def test_delete_saved(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cookie.txt")
            n.save_user_session("user_session_1_abc", path=path)
            self.assertTrue(n.delete_saved_session(path))
            self.assertFalse(n.has_saved_session(path))

    def test_delete_missing_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(n.delete_saved_session(path=os.path.join(d, "nope.txt")))

    def test_cookie_file_path_is_next_to_script(self):
        self.assertEqual(n.cookie_file_path(), os.path.join(n.script_dir(), "cookie.txt"))

    def test_read_candidates_are_script_dir_only(self):
        # 読み書きの対象を1箇所（nicoids.py と同じフォルダ）に揃える
        self.assertEqual(n.cookie_file_candidates(), [n.cookie_file_path()])


class ResolveSessionTest(unittest.TestCase):
    def test_cookie(self):
        with mock.patch.object(n, "load_user_session", return_value=("cookie_val", "/p")):
            self.assertEqual(n.resolve_session(), ("cookie_val", "cookie"))

    def test_invalid_cookie(self):
        with mock.patch.object(n, "load_user_session", return_value=(None, "/p")):
            self.assertEqual(n.resolve_session(), (None, "invalid_cookie"))

    def test_nothing(self):
        with mock.patch.object(n, "load_user_session", return_value=(None, None)):
            self.assertEqual(n.resolve_session(), (None, None))


# ---------------------------------------------------------------------------
# parse_target
# ---------------------------------------------------------------------------
class ParseTargetTest(unittest.TestCase):
    def test_series_url(self):
        self.assertEqual(
            n.parse_target("https://www.nicovideo.jp/series/228685"),
            (n.KIND_SERIES, "228685"),
        )

    def test_mylist_url(self):
        self.assertEqual(
            n.parse_target("https://www.nicovideo.jp/mylist/1754716"),
            (n.KIND_MYLIST, "1754716"),
        )

    def test_user_series_url(self):
        # ユーザーページから開いたシリーズ（/user/{uid}/series/{id}）も受け付ける
        self.assertEqual(
            n.parse_target("https://www.nicovideo.jp/user/123/series/228685"),
            (n.KIND_SERIES, "228685"),
        )

    def test_user_mylist_url(self):
        self.assertEqual(
            n.parse_target("https://www.nicovideo.jp/user/123/mylist/1754716"),
            (n.KIND_MYLIST, "1754716"),
        )

    def test_tag_url(self):
        kind, url = n.parse_target("https://www.nicovideo.jp/tag/xx")
        self.assertEqual(kind, n.KIND_SEARCH)
        self.assertTrue(url.startswith("https://www.nicovideo.jp/tag/"))

    def test_number_only_is_series(self):
        self.assertEqual(n.parse_target("228685"), (n.KIND_SERIES, "228685"))

    def test_force_mylist(self):
        self.assertEqual(
            n.parse_target("228685", force_type=n.TYPE_MYLIST),
            (n.KIND_MYLIST, "228685"),
        )

    def test_empty(self):
        self.assertIsNone(n.parse_target(""))
        self.assertIsNone(n.parse_target("   "))


# ---------------------------------------------------------------------------
# URL 整形
# ---------------------------------------------------------------------------
class UrlTest(unittest.TestCase):
    def test_normalize_encodes_non_ascii(self):
        out = n.normalize_search_url("https://www.nicovideo.jp/tag/けもの")
        self.assertIn("%E3%81%91", out)
        self.assertNotIn("け", out)

    def test_normalize_space_to_plus(self):
        self.assertEqual(
            n.normalize_search_url("https://www.nicovideo.jp/search/a b"),
            "https://www.nicovideo.jp/search/a+b",
        )

    def test_normalize_keeps_encoded(self):
        url = "https://www.nicovideo.jp/search/%E3%81%82+foo-bar"
        self.assertEqual(n.normalize_search_url(url), url)

    def test_set_query_param_add(self):
        self.assertEqual(n.set_query_param("https://x/search/a", "page", 2),
                         "https://x/search/a?page=2")

    def test_set_query_param_append(self):
        self.assertEqual(n.set_query_param("https://x/search/a?sort=f", "page", 2),
                         "https://x/search/a?sort=f&page=2")

    def test_set_query_param_replace(self):
        self.assertEqual(n.set_query_param("https://x/search/a?page=1", "page", 3),
                         "https://x/search/a?page=3")


# ---------------------------------------------------------------------------
# 表示用の整形
# ---------------------------------------------------------------------------
class FormatTest(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(n.format_duration(1420), "23:40")
        self.assertEqual(n.format_duration(3661), "1:01:01")
        self.assertEqual(n.format_duration(59), "0:59")
        self.assertEqual(n.format_duration(None), "")
        self.assertEqual(n.format_duration(""), "")
        self.assertEqual(n.format_duration("abc"), "")

    def test_format_count(self):
        self.assertEqual(n.format_count(107373), "107373")
        self.assertEqual(n.format_count(None), "")
        self.assertEqual(n.format_count(""), "")

    def test_sanitize_cell(self):
        self.assertEqual(n.sanitize_cell("a\tb\nc  d"), "a b c d")
        self.assertEqual(n.sanitize_cell(None), "")

    def test_strip_prefix(self):
        self.assertEqual(n.strip_prefix("so33963154"), "33963154")
        self.assertEqual(n.strip_prefix("sm9"), "9")
        self.assertEqual(n.strip_prefix("123"), "123")

    def test_parse_max_items(self):
        self.assertIsNone(n.parse_max_items(""))
        self.assertIsNone(n.parse_max_items("   "))
        self.assertIsNone(n.parse_max_items("abc"))
        self.assertIsNone(n.parse_max_items("0"))
        self.assertIsNone(n.parse_max_items("-5"))
        self.assertEqual(n.parse_max_items("50"), 50)
        self.assertEqual(n.parse_max_items("1,000"), 1000)

    def test_parse_interval(self):
        self.assertEqual(n.parse_interval(""), n.THUMB_DEFAULT_INTERVAL)
        self.assertEqual(n.parse_interval("abc"), n.THUMB_DEFAULT_INTERVAL)
        self.assertEqual(n.parse_interval("nan"), n.THUMB_DEFAULT_INTERVAL)
        self.assertEqual(n.parse_interval("1"), 1.0)
        self.assertEqual(n.parse_interval("0.1"), n.THUMB_MIN_INTERVAL)
        self.assertEqual(n.parse_interval("100"), n.THUMB_MAX_INTERVAL)


# ---------------------------------------------------------------------------
# サムネイル: 抽出・URL解決・ファイル名
# ---------------------------------------------------------------------------
def _thumb_dict(vid="so1"):
    return {
        "url": f"https://img.example.invalid/{vid}_std.jpg",
        "largeUrl": f"https://img.example.invalid/{vid}_large.jpg",
        "nHdUrl": f"https://img.example.invalid/{vid}_nhd.jpg",
    }


class ThumbnailExtractTest(unittest.TestCase):
    def test_series_item_extracts_thumbnail(self):
        item = {"meta": {"id": "so33963154"}, "video": {
            "id": "so33963154", "title": "タイトル", "thumbnail": _thumb_dict("so33963154"),
        }}
        info = n._video_info_from_item(item)
        self.assertEqual(info["thumbnail"]["largeUrl"],
                         "https://img.example.invalid/so33963154_large.jpg")

    def test_search_style_item_extracts_thumbnail(self):
        # 検索の items[] は video でラップされていない形
        item = {"id": "sm9", "title": "x", "thumbnail": _thumb_dict("sm9")}
        info = n._video_info_from_item(item)
        self.assertEqual(info["thumbnail"]["nHdUrl"],
                         "https://img.example.invalid/sm9_nhd.jpg")

    def test_missing_thumbnail_becomes_empty_dict(self):
        info = n._video_info_from_item({"id": "sm9", "title": "x"})
        self.assertEqual(info["thumbnail"], {"url": "", "largeUrl": "", "nHdUrl": ""})


class ResolveThumbnailUrlTest(unittest.TestCase):
    def _video(self, thumb):
        return {"id": "so1", "thumbnail": thumb}

    def test_each_size(self):
        v = self._video(_thumb_dict("so1"))
        self.assertIn("_nhd.", n.resolve_thumbnail_url(v, n.THUMB_NHD))
        self.assertIn("_large.", n.resolve_thumbnail_url(v, n.THUMB_LARGE))
        self.assertIn("_std.", n.resolve_thumbnail_url(v, n.THUMB_STD))

    def test_falls_back_to_other_size(self):
        # 選んだサイズが無ければ高画質→低画質の順で代替する
        thumb = {"url": "https://img.example.invalid/std.jpg"}
        self.assertEqual(
            n.resolve_thumbnail_url(self._video(thumb), n.THUMB_LARGE),
            "https://img.example.invalid/std.jpg",
        )

    def test_no_thumbnail_returns_none(self):
        self.assertIsNone(n.resolve_thumbnail_url({"id": "so1"}, n.THUMB_LARGE))
        self.assertIsNone(n.resolve_thumbnail_url(self._video({}), n.THUMB_LARGE))


class SanitizeFilenameTest(unittest.TestCase):
    def test_invalid_chars_become_spaces(self):
        out = n.sanitize_filename('a/b\\c:d*e?f"g<h>i|j')
        self.assertEqual(out, "a b c d e f g h i j")

    def test_control_chars_and_whitespace(self):
        self.assertEqual(n.sanitize_filename("a\tb\nc  d"), "a b c d")

    def test_trims_trailing_dot_and_space(self):
        self.assertEqual(n.sanitize_filename("a. "), "a")
        self.assertEqual(n.sanitize_filename("..a.."), "a")

    def test_max_len(self):
        out = n.sanitize_filename("あ" * 200)
        self.assertLessEqual(len(out), n._THUMB_FILENAME_MAX)

    def test_empty(self):
        self.assertEqual(n.sanitize_filename(""), "")
        self.assertEqual(n.sanitize_filename(None), "")


class ThumbnailFilenameTest(unittest.TestCase):
    def test_with_title(self):
        v = {"id": "so33963154", "title": "テスト 動画"}
        self.assertEqual(n.thumbnail_filename(v), "so33963154_テスト 動画.jpg")

    def test_title_sanitized(self):
        v = {"id": "sm9", "title": "a/b:c"}
        self.assertEqual(n.thumbnail_filename(v), "sm9_a b c.jpg")

    def test_without_title(self):
        v = {"id": "sm9", "title": ""}
        self.assertEqual(n.thumbnail_filename(v), "sm9.jpg")


# ---------------------------------------------------------------------------
# download_thumbnails
# ---------------------------------------------------------------------------
class DownloadThumbnailsTest(unittest.TestCase):
    def _video(self, vid, with_thumb=True, title="題名"):
        return {
            "id": vid,
            "title": title,
            "thumbnail": _thumb_dict(vid) if with_thumb else {},
        }

    def test_saves_files(self):
        videos = [self._video("so1"), self._video("so2")]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(n, "http_get_bytes", return_value=b"JPEGDATA") as get, \
                mock.patch.object(n.time, "sleep") as sleep:
            saved, skipped, failures, reason = n.download_thumbnails(videos, d)
            saved_ok = all(
                os.path.isfile(os.path.join(d, f"so{i}_題名.jpg")) for i in (1, 2)
            )
        self.assertEqual((saved, skipped, failures, reason), (2, 0, [], None))
        self.assertEqual(get.call_count, 2)
        self.assertTrue(saved_ok)
        self.assertEqual(sleep.call_count, 2)   # 保存後に間隔を空ける

    def test_skips_existing_without_request(self):
        videos = [self._video("so1")]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(n, "http_get_bytes") as get, \
                mock.patch.object(n.time, "sleep"):
            # 先に同名ファイルを作っておく
            open(os.path.join(d, "so1_題名.jpg"), "wb").close()
            saved, skipped, failures, reason = n.download_thumbnails(videos, d)
        self.assertEqual((saved, skipped, failures, reason), (0, 1, [], None))
        self.assertFalse(get.called)

    def test_respects_max_items(self):
        videos = [self._video(f"so{i}") for i in range(3)]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(n, "http_get_bytes", return_value=b"x"), \
                mock.patch.object(n.time, "sleep"):
            saved, _, _, _ = n.download_thumbnails(videos, d, max_items=2)
        self.assertEqual(saved, 2)

    def test_http_failure_recorded_not_raised(self):
        err = urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)
        videos = [self._video("so1")]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(n, "http_get_bytes", side_effect=err), \
                mock.patch.object(n.time, "sleep"):
            saved, _, failures, reason = n.download_thumbnails(videos, d)
        self.assertEqual(saved, 0)
        self.assertIsNone(reason)
        self.assertEqual(failures[0], ("so1", "HTTP 404"))

    def test_stops_after_consecutive_failures(self):
        err = urllib.error.HTTPError("https://x", 503, "Service Unavailable", {}, None)
        videos = [self._video(f"so{i}") for i in range(30)]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(n, "http_get_bytes", side_effect=err) as get, \
                mock.patch.object(n.time, "sleep"):
            _, _, failures, reason = n.download_thumbnails(videos, d)
        self.assertEqual(reason, "too_many_failures")
        self.assertEqual(get.call_count, n.THUMB_MAX_CONSECUTIVE_FAILURES)
        self.assertEqual(len(failures), n.THUMB_MAX_CONSECUTIVE_FAILURES)

    def test_missing_url_counted_as_failure_without_request(self):
        videos = [self._video("so1", with_thumb=False)]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(n, "http_get_bytes") as get:
            saved, _, failures, reason = n.download_thumbnails(videos, d)
        self.assertEqual(saved, 0)
        self.assertFalse(get.called)
        self.assertEqual(failures[0], ("so1", "サムネイルURLなし"))
        self.assertIsNone(reason)

    def test_cancel_stops_loop(self):
        videos = [self._video(f"so{i}") for i in range(5)]
        state = {"n": 0}

        def should_stop():
            state["n"] += 1
            return state["n"] > 2   # 2件处理后に停止判定

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(n, "http_get_bytes", return_value=b"x"), \
                mock.patch.object(n.time, "sleep"):
            saved, _, _, reason = n.download_thumbnails(
                videos, d, should_stop=should_stop,
            )
        self.assertEqual(reason, "cancelled")
        self.assertEqual(saved, 2)


# ---------------------------------------------------------------------------
# HTTP ヘッダ（ニコ動の担当者からの依頼を守る）
# ---------------------------------------------------------------------------
class UserAgentTest(unittest.TestCase):
    def test_user_agent_is_identifiable_tool_name(self):
        # ニコ動の担当者から「識別できるツール名にしてほしい」と依頼されている
        self.assertEqual(n.USER_AGENT, "WeeklyNicoranProgram")

    def test_user_agent_has_no_japanese(self):
        # 「日本語文字は入れない」という条件を守る
        self.assertTrue(n.USER_AGENT.isascii(), n.USER_AGENT)

    def test_requests_use_the_user_agent(self):
        # 3つの取得経路（nvapi / HTML / サムネイル）の両方に乗っていること
        captured = []

        def fake_urlopen(req, timeout=None):
            captured.append(req.get_header("User-agent"))
            raise urllib.error.URLError("stop")   # 実通信はしない

        with mock.patch.object(n.urllib.request, "urlopen", side_effect=fake_urlopen), \
                mock.patch.object(n.time, "sleep"):   # リトライ待ちを飛ばす
            for getter in (n.http_get_json, n.http_get_text, n.http_get_bytes):
                with self.assertRaises(urllib.error.URLError):
                    getter("https://example.invalid/")
        self.assertTrue(captured)
        self.assertEqual(set(captured), {n.USER_AGENT})


# ---------------------------------------------------------------------------
# GUI スモークテスト（Tk が使える環境のみ）
# ---------------------------------------------------------------------------
def _tk_available():
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


class _FakeDialog:
    """open_login_dialog のテスト用ダミー（wait_window を挟まずに検証する）。"""

    def __init__(self, action=None, value=None, exists=True):
        self.action = action
        self.value = value
        self._exists = exists
        self.lifted = False

    def winfo_exists(self):
        return self._exists

    def lift(self):
        self.lifted = True

    def focus_set(self):
        pass


def _widget_texts(widget):
    """ウィジェット木の text を集める（ボタンの有無の確認用）。"""
    texts = []
    for w in widget.winfo_children():
        try:
            texts.append(w.cget("text"))
        except Exception:
            pass
        texts += _widget_texts(w)
    return texts


class GuiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 収集時に Tk を生成しないよう、ここで判定する
        if not _tk_available():
            raise unittest.SkipTest("Tk が使えない環境")

    def setUp(self):
        self.app = n.App()
        self.app.update_idletasks()

    def tearDown(self):
        self.app.destroy()

    # -- 画面の生成 --------------------------------------------------------
    def test_app_build(self):
        self.assertIn("ログイン:", self.app.login_state_var.get())

    # -- LoginDialog 単体 --------------------------------------------------
    def test_dialog_save_normalizes(self):
        with mock.patch.object(n.messagebox, "showwarning"):
            dlg = n.LoginDialog(self.app)
            self.app.update_idletasks()
            dlg.value_var.set("Cookie: user_session=user_session_9_zz; a=1")
            dlg._on_save()
        self.assertEqual(dlg.action, "save")
        self.assertEqual(dlg.value, "user_session_9_zz")

    def test_dialog_rejects_non_session(self):
        with mock.patch.object(n.messagebox, "showwarning") as warn:
            dlg = n.LoginDialog(self.app)
            self.app.update_idletasks()
            dlg.value_var.set("https://example.com/whatever")
            dlg._on_save()
            self.assertTrue(warn.called)
        self.assertIsNone(dlg.action)
        self.assertTrue(dlg.winfo_exists())   # 閉じずに再入力を促す
        dlg.destroy()

    def test_dialog_empty_save_warns(self):
        with mock.patch.object(n.messagebox, "showwarning") as warn:
            dlg = n.LoginDialog(self.app)
            self.app.update_idletasks()
            dlg.value_var.set("   ")
            dlg._on_save()
            self.assertTrue(warn.called)
        self.assertIsNone(dlg.action)
        self.assertTrue(dlg.winfo_exists())
        dlg.destroy()

    def test_dialog_clear_only_clears_entry(self):
        # 「クリア」は入力欄を空にするだけで、閉じないしファイルにも触らない
        dlg = n.LoginDialog(self.app)
        self.app.update_idletasks()
        dlg.value_var.set("user_session_1_ab")
        dlg._on_clear()
        self.assertEqual(dlg.value_var.get(), "")
        self.assertIsNone(dlg.action)
        self.assertTrue(dlg.winfo_exists())
        dlg.destroy()

    def test_dialog_delete(self):
        dlg = n.LoginDialog(self.app, saved_exists=True)
        self.app.update_idletasks()
        with mock.patch.object(n.messagebox, "askyesno", return_value=True) as ask:
            dlg._on_delete()
            self.assertTrue(ask.called)   # 保存済みがあるときは確認する
        self.assertEqual(dlg.action, "delete")
        self.assertIsNone(dlg.value)

    def test_dialog_delete_declined_keeps_open(self):
        dlg = n.LoginDialog(self.app, saved_exists=True)
        self.app.update_idletasks()
        with mock.patch.object(n.messagebox, "askyesno", return_value=False):
            dlg._on_delete()
        self.assertIsNone(dlg.action)
        self.assertTrue(dlg.winfo_exists())
        dlg.destroy()

    def test_dialog_delete_without_saved_skips_confirm(self):
        dlg = n.LoginDialog(self.app, saved_exists=False)
        self.app.update_idletasks()
        with mock.patch.object(n.messagebox, "askyesno") as ask:
            dlg._on_delete()
            self.assertFalse(ask.called)   # 保存が無ければ確認不要
        self.assertEqual(dlg.action, "delete")

    def test_dialog_button_labels_are_explicit(self):
        dlg = n.LoginDialog(self.app)
        self.app.update_idletasks()
        texts = _widget_texts(dlg)
        for expected in ("保存する", "ログイン情報を削除する", "キャンセル", "クリア"):
            self.assertIn(expected, texts)
        self.assertNotIn("OK", texts)   # 紛らわしい「OK」は廃止
        dlg.destroy()

    def test_dialog_cancel(self):
        dlg = n.LoginDialog(self.app)
        self.app.update_idletasks()
        dlg._on_cancel()
        self.assertIsNone(dlg.action)
        self.assertIsNone(dlg.value)

    def test_dialog_escape_cancels(self):
        # 回帰テスト: Esc のバインドがハンドラを呼び忘れていないこと
        dlg = n.LoginDialog(self.app)
        self.app.update()
        dlg.focus_force()
        self.app.update()
        dlg.action = "sentinel"
        dlg.event_generate("<Escape>", when="now")
        self.app.update()
        self.assertIsNone(dlg.action)
        self.assertFalse(dlg.winfo_exists())

    def test_dialog_show_toggle(self):
        dlg = n.LoginDialog(self.app)
        self.app.update_idletasks()
        self.assertEqual(dlg.entry.cget("show"), "●")
        dlg.show_var.set(True)
        dlg._toggle_show()
        self.assertEqual(dlg.entry.cget("show"), "")
        dlg.destroy()

    def test_dialog_entry_is_wide_enough(self):
        # user_session は 80 文字以上になるため、入力欄がある程度広いこと
        dlg = n.LoginDialog(self.app)
        self.app.update_idletasks()
        self.assertGreaterEqual(int(dlg.entry.cget("width")), 90)
        self.assertTrue(dlg.resizable())   # 長い値のとき広げられる
        dlg.destroy()

    # -- open_login_dialog の状態遷移 -------------------------------------
    def test_open_dialog_save_writes(self):
        with mock.patch.object(n, "LoginDialog",
                               return_value=_FakeDialog("save", "user_session_1_ab")), \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch.object(n, "save_user_session",
                                  return_value=n.cookie_file_path()) as save:
            self.app.open_login_dialog()
        save.assert_called_once_with("user_session_1_ab")
        self.assertIn("保存しました", self.app.status_var.get())

    def test_open_dialog_delete(self):
        with mock.patch.object(n, "LoginDialog", return_value=_FakeDialog("delete")), \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch.object(n, "delete_saved_session", return_value=True) as delete:
            self.app.open_login_dialog()
        self.assertTrue(delete.called)
        self.assertIn("削除しました", self.app.status_var.get())

    def test_open_dialog_delete_clears_relogin(self):
        # 回帰: 403 で「要再ログイン」のときに削除したら、表示も解除される
        self.app._mark_relogin()
        with mock.patch.object(n, "LoginDialog", return_value=_FakeDialog("delete")), \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch.object(n, "delete_saved_session", return_value=True):
            self.app.open_login_dialog()
        self.assertFalse(self.app._relogin_needed)
        self.assertNotIn("要再ログイン", self.app.login_state_var.get())

    def test_open_dialog_save_success_clears_relogin(self):
        self.app._mark_relogin()
        with mock.patch.object(n, "LoginDialog",
                               return_value=_FakeDialog("save", "user_session_1_ab")), \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch.object(n, "save_user_session",
                                  return_value=n.cookie_file_path()):
            self.app.open_login_dialog()
        self.assertFalse(self.app._relogin_needed)

    def test_open_dialog_save_failure_keeps_relogin(self):
        # 保存に失敗したのに「要再ログイン」が消えると、状態が嘘になる
        self.app._mark_relogin()
        with mock.patch.object(n, "LoginDialog",
                               return_value=_FakeDialog("save", "user_session_1_ab")), \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch.object(n, "save_user_session", side_effect=OSError("denied")), \
                mock.patch.object(n.messagebox, "showerror") as err:
            self.app.open_login_dialog()
        self.assertTrue(err.called)
        self.assertTrue(self.app._relogin_needed)

    def test_delete_failure_shows_error(self):
        with mock.patch.object(n, "delete_saved_session", side_effect=OSError("denied")), \
                mock.patch.object(n.messagebox, "showerror") as err:
            self.app._delete_saved_session()
        self.assertTrue(err.called)

    def test_save_failure_shows_error(self):
        with mock.patch.object(n, "save_user_session", side_effect=OSError("denied")), \
                mock.patch.object(n.messagebox, "showerror") as err:
            self.app._save_session("user_session_1_ab")
        self.assertTrue(err.called)

    def test_open_dialog_cancel_does_nothing(self):
        with mock.patch.object(n, "LoginDialog", return_value=_FakeDialog(None)), \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch.object(n, "save_user_session") as save, \
                mock.patch.object(n, "delete_saved_session") as delete:
            self.app.open_login_dialog()
        self.assertFalse(save.called)
        self.assertFalse(delete.called)

    def test_open_dialog_passes_saved_state(self):
        with mock.patch.object(n, "LoginDialog") as ctor, \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch.object(n, "has_saved_session", return_value=True):
            ctor.return_value = _FakeDialog(None)
            self.app.open_login_dialog()
        self.assertTrue(ctor.call_args.kwargs["saved_exists"])

    def test_open_dialog_passes_no_saved_state(self):
        with mock.patch.object(n, "LoginDialog") as ctor, \
                mock.patch.object(self.app, "wait_window"), \
                mock.patch.object(n, "has_saved_session", return_value=False):
            ctor.return_value = _FakeDialog(None)
            self.app.open_login_dialog()
        self.assertFalse(ctor.call_args.kwargs["saved_exists"])

    def test_open_dialog_no_duplicate(self):
        existing = _FakeDialog()
        self.app._login_dlg = existing
        with mock.patch.object(n, "LoginDialog") as ctor:
            self.app.open_login_dialog()
        self.assertFalse(ctor.called)
        self.assertTrue(existing.lifted)

    # -- サムネイル保存 ----------------------------------------------------
    def test_thumb_row_exists(self):
        texts = _widget_texts(self.app)
        self.assertIn("サムネイル保存:", texts)
        self.assertIn("保存…", texts)

    def test_get_max_items_parses_field(self):
        self.app.max_var.set("50")
        self.assertEqual(self.app.get_max_items(), 50)
        self.app.max_var.set("")
        self.assertIsNone(self.app.get_max_items())

    def test_on_download_thumbs_requires_results(self):
        with mock.patch.object(n.filedialog, "askdirectory") as ask:
            self.app.on_download_thumbs()
        self.assertFalse(ask.called)
        self.assertIn("先に「取得」", self.app.status_var.get())

    def test_on_download_thumbs_cancelled_directory(self):
        self.app._videos = [{"id": "so1", "title": "", "thumbnail": {}}]
        with mock.patch.object(n.filedialog, "askdirectory", return_value=""), \
                mock.patch.object(n, "download_thumbnails") as dl:
            self.app.on_download_thumbs()
        self.assertFalse(dl.called)
        self.assertFalse(self.app._busy)

    def test_on_download_thumbs_passes_options(self):
        self.app._videos = [{"id": "so1", "title": "", "thumbnail": {}}]
        self.app.thumb_max_var.set("10")
        self.app.thumb_interval_var.set("2")
        with mock.patch.object(n.filedialog, "askdirectory", return_value="C:/thumbs"), \
                mock.patch.object(n, "download_thumbnails", return_value=(0, 0, [], None)), \
                mock.patch.object(n.threading, "Thread") as thread:
            self.app.on_download_thumbs()
        args = thread.call_args.kwargs["args"]
        self.assertEqual(args, ("C:/thumbs", n.THUMB_LARGE, 10, 2.0))

    def test_thumb_worker_reports_summary(self):
        self.app._videos = [{"id": "so1", "title": "", "thumbnail": {}}]
        with mock.patch.object(n, "download_thumbnails",
                               return_value=(3, 1, [], None)):
            self.app._thumb_worker("C:/thumbs", n.THUMB_LARGE, None, 0.5)
            self.app.update()
        self.assertIn("保存3件", self.app.status_var.get())
        self.assertIn("スキップ1件", self.app.status_var.get())
        self.assertFalse(self.app._busy)

    def test_thumb_worker_failures_show_warning(self):
        self.app._videos = [{"id": "so1", "title": "", "thumbnail": {}}]
        failures = [("so1", "HTTP 404")]
        with mock.patch.object(n, "download_thumbnails",
                               return_value=(0, 0, failures, None)), \
                mock.patch.object(n.messagebox, "showwarning") as warn:
            self.app._thumb_worker("C:/thumbs", n.THUMB_LARGE, None, 0.5)
            self.app.update()
        self.assertTrue(warn.called)
        self.assertIn("HTTP 404", warn.call_args[0][1])

    def test_thumb_worker_cancelled_summary(self):
        self.app._videos = [{"id": "so1", "title": "", "thumbnail": {}}]
        with mock.patch.object(n, "download_thumbnails",
                               return_value=(1, 0, [], "cancelled")):
            self.app._thumb_worker("C:/thumbs", n.THUMB_LARGE, None, 0.5)
            self.app.update()
        self.assertIn("中断しました", self.app.status_var.get())

    def test_thumb_worker_too_many_failures(self):
        self.app._videos = [{"id": "so1", "title": "", "thumbnail": {}}]
        with mock.patch.object(n, "download_thumbnails",
                               return_value=(0, 0, [("so1", "HTTP 503")], "too_many_failures")), \
                mock.patch.object(n.messagebox, "showwarning"):   # モーダルで止まらないようにする
            self.app._thumb_worker("C:/thumbs", n.THUMB_LARGE, None, 0.5)
            self.app.update()
        self.assertIn("打ち切り", self.app.status_var.get())

    # -- 状態ラベル --------------------------------------------------------
    def test_indicator_labels(self):
        cases = [
            (("v", "cookie"), "設定済み（cookie.txt）"),
            ((None, "invalid_cookie"), "cookie.txt を読み取れません"),
            ((None, None), "未設定"),
        ]
        for resolved, expected in cases:
            with mock.patch.object(n, "resolve_session", return_value=resolved):
                self.app.update_login_indicator()
            self.assertEqual(self.app.login_state_var.get(), "ログイン: " + expected)

    def test_relogin_label_survives_recompute(self):
        self.app._mark_relogin()
        self.assertEqual(self.app.login_state_var.get(), "ログイン: 要再ログイン")
        with mock.patch.object(n, "resolve_session", return_value=("v", "cookie")):
            self.app.update_login_indicator()
        self.assertEqual(self.app.login_state_var.get(), "ログイン: 要再ログイン")

    # -- _worker -----------------------------------------------------------
    def test_worker_403_marks_relogin(self):
        err = urllib.error.HTTPError("https://x", 403, "Forbidden", {}, None)
        with mock.patch.object(n, "fetch_mylist", side_effect=err), \
                mock.patch.object(self.app, "_fail") as fail:
            self.app._worker(n.KIND_MYLIST, "1", None, "user_session_1_ab")
            self.app.update()   # after(0, _mark_relogin) を処理させる
        self.assertTrue(fail.called)
        self.assertIn("403", fail.call_args[0][0])
        self.assertEqual(self.app.login_state_var.get(), "ログイン: 要再ログイン")

    def test_worker_without_session_fails(self):
        with mock.patch.object(n, "fetch_mylist") as fetch, \
                mock.patch.object(self.app, "_fail") as fail:
            self.app._worker(n.KIND_MYLIST, "1", None, None)
        self.assertFalse(fetch.called)
        self.assertIn("ログイン設定", fail.call_args[0][0])

    def test_worker_mylist_success_clears_relogin(self):
        self.app._relogin_needed = True
        with mock.patch.object(n, "fetch_mylist", return_value=([], None, None)):
            self.app._worker(n.KIND_MYLIST, "1", None, "user_session_1_ab")
            self.app.update()
        self.assertFalse(self.app._relogin_needed)

    def test_worker_series_success_keeps_relogin(self):
        # 認証不要の取得で「要再ログイン」が消えないこと
        self.app._mark_relogin()
        with mock.patch.object(n, "fetch_series", return_value=([], None, None)):
            self.app._worker(n.KIND_SERIES, "228685", None, None)
            self.app.update()
        self.assertTrue(self.app._relogin_needed)
        self.assertEqual(self.app.login_state_var.get(), "ログイン: 要再ログイン")

    # -- _ensure_session ---------------------------------------------------
    def test_ensure_session_returns_existing(self):
        with mock.patch.object(n, "resolve_session", return_value=("user_session_1_ab", "cookie")):
            self.assertEqual(self.app._ensure_session(), "user_session_1_ab")

    def test_ensure_session_declined(self):
        with mock.patch.object(n, "resolve_session", return_value=(None, None)), \
                mock.patch.object(n.messagebox, "askyesno", return_value=False):
            self.assertIsNone(self.app._ensure_session())

    def test_ensure_session_via_dialog(self):
        # ダイアログで保存された後、cookie.txt から解決できるようになる
        with mock.patch.object(n, "resolve_session",
                               side_effect=[(None, None), ("user_session_1_ab", "cookie")]), \
                mock.patch.object(n.messagebox, "askyesno", return_value=True), \
                mock.patch.object(self.app, "open_login_dialog") as open_dlg:
            self.assertEqual(self.app._ensure_session(), "user_session_1_ab")
        self.assertTrue(open_dlg.called)

    def test_ensure_session_still_missing_after_dialog(self):
        with mock.patch.object(n, "resolve_session", return_value=(None, None)), \
                mock.patch.object(n.messagebox, "askyesno", return_value=True), \
                mock.patch.object(self.app, "open_login_dialog"):
            self.assertIsNone(self.app._ensure_session())


if __name__ == "__main__":
    unittest.main()
