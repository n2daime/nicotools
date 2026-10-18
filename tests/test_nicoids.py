# -*- coding: utf-8 -*-
"""nicoids.py の単体テスト。

- ネットワークは一切叩かない（HTTP はモック不要な純粋関数のみを対象にする）。
- 実トークンは使わない。すべてダミー値。

実行（リポジトリ直下で）:
    python -m unittest discover -s tests
"""

import os
import tempfile
import unittest
from unittest import mock

import nicoids as n


# ---------------------------------------------------------------------------
# extract_user_session
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
        self.assertEqual(n.extract_user_session("some_random_value"), "some_random_value")

    def test_multiline_without_match(self):
        self.assertIsNone(n.extract_user_session("foo\nbar\nbaz"))


# ---------------------------------------------------------------------------
# load_user_session / resolve_session
# ---------------------------------------------------------------------------
class LoadUserSessionTest(unittest.TestCase):
    def _write(self, directory, text):
        path = os.path.join(directory, "cookie.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_reads_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "user_session_1_abc\n")
            self.assertEqual(n.load_user_session(paths=[path]), ("user_session_1_abc", path))

    def test_file_without_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "hello\nworld\n")
            self.assertEqual(n.load_user_session(paths=[path]), (None, path))

    def test_missing_file(self):
        missing = os.path.join(tempfile.gettempdir(), "no_such_cookie_9f3a.txt")
        self.assertEqual(n.load_user_session(paths=[missing]), (None, None))

    def test_directory_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(n.load_user_session(paths=[d]), (None, None))

    def test_first_candidate_wins(self):
        with tempfile.TemporaryDirectory() as d:
            good = self._write(d, "user_session_1_abc\n")
            missing = os.path.join(d, "cookie.txt.missing")
            self.assertEqual(n.load_user_session(paths=[missing, good]),
                             ("user_session_1_abc", good))


class ResolveSessionTest(unittest.TestCase):
    def test_gui_wins_over_cookie(self):
        with mock.patch.object(n, "load_user_session", return_value=("cookie_val", "/p")):
            self.assertEqual(n.resolve_session("gui_val"), ("gui_val", "gui"))

    def test_cookie_fallback(self):
        with mock.patch.object(n, "load_user_session", return_value=("cookie_val", "/p")):
            self.assertEqual(n.resolve_session(None), ("cookie_val", "cookie"))

    def test_invalid_cookie(self):
        with mock.patch.object(n, "load_user_session", return_value=(None, "/p")):
            self.assertEqual(n.resolve_session(None), (None, "invalid_cookie"))

    def test_nothing(self):
        with mock.patch.object(n, "load_user_session", return_value=(None, None)):
            self.assertEqual(n.resolve_session(None), (None, None))


# ---------------------------------------------------------------------------
# parse_target
# ---------------------------------------------------------------------------
class ParseTargetTest(unittest.TestCase):
    def test_series_url(self):
        self.assertEqual(
            n.parse_target("https://www.nicovideo.jp/series/62864"),
            (n.KIND_SERIES, "62864"),
        )

    def test_mylist_url(self):
        self.assertEqual(
            n.parse_target("https://www.nicovideo.jp/mylist/79588643"),
            (n.KIND_MYLIST, "79588643"),
        )

    def test_user_mylist_url(self):
        self.assertEqual(
            n.parse_target("https://www.nicovideo.jp/user/123/mylist/79588643"),
            (n.KIND_MYLIST, "79588643"),
        )

    def test_tag_url(self):
        kind, url = n.parse_target("https://www.nicovideo.jp/tag/xx")
        self.assertEqual(kind, n.KIND_SEARCH)
        self.assertTrue(url.startswith("https://www.nicovideo.jp/tag/"))

    def test_number_only_is_series(self):
        self.assertEqual(n.parse_target("62864"), (n.KIND_SERIES, "62864"))

    def test_force_mylist(self):
        self.assertEqual(
            n.parse_target("62864", force_type=n.TYPE_MYLIST),
            (n.KIND_MYLIST, "62864"),
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


TK_OK = _tk_available()


@unittest.skipUnless(TK_OK, "Tk が使えない環境")
class GuiSmokeTest(unittest.TestCase):
    def test_app_build(self):
        app = n.App()
        app.update_idletasks()
        self.assertIn("ログイン:", app.login_state_var.get())
        app.destroy()

    def test_login_dialog_ok_normalizes(self):
        app = n.App()
        app.update_idletasks()
        with mock.patch.object(n.messagebox, "showwarning"):
            dlg = n.LoginDialog(app, current=None)
            app.update_idletasks()
            dlg.value_var.set("Cookie: user_session=user_session_9_zz; a=1")
            dlg._on_ok()
        self.assertEqual(dlg.action, "ok")
        self.assertEqual(dlg.value, "user_session_9_zz")
        app.destroy()

    def test_login_dialog_empty_ok_warns(self):
        app = n.App()
        app.update_idletasks()
        with mock.patch.object(n.messagebox, "showwarning") as warn:
            dlg = n.LoginDialog(app, current=None)
            app.update_idletasks()
            dlg.value_var.set("   ")
            dlg._on_ok()
            self.assertTrue(warn.called)
        self.assertIsNone(dlg.action)
        self.assertTrue(dlg.winfo_exists())
        dlg.destroy()
        app.destroy()

    def test_ensure_session_declined(self):
        app = n.App()
        app.update_idletasks()
        with mock.patch.object(n, "resolve_session", return_value=(None, None)), \
                mock.patch.object(n.messagebox, "askyesno", return_value=False):
            self.assertIsNone(app._ensure_session())
        app.destroy()

    def test_ensure_session_via_dialog(self):
        app = n.App()
        app.update_idletasks()
        with mock.patch.object(n, "resolve_session",
                               side_effect=[(None, None), ("user_session_1_ab", "gui")]), \
                mock.patch.object(app, "update_login_indicator"), \
                mock.patch.object(n.messagebox, "askyesno", return_value=True), \
                mock.patch.object(app, "open_login_dialog") as open_dlg:
            self.assertEqual(app._ensure_session(), "user_session_1_ab")
            self.assertTrue(open_dlg.called)
        app.destroy()


if __name__ == "__main__":
    unittest.main()
