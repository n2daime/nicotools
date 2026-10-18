# -*- coding: utf-8 -*-
"""nicoids.py の単体テスト。

- ネットワークは一切叩かない（HTTP はモック不要な純粋関数のみを対象にする）。
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


class ResolveSessionTest(unittest.TestCase):
    def test_gui_wins_over_cookie(self):
        with mock.patch.object(n, "load_user_session", return_value=("cookie_val", "/p")) as load:
            self.assertEqual(n.resolve_session("gui_val"), ("gui_val", "gui"))
            load.assert_not_called()   # GUI 値があれば cookie.txt は読まない

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
    def test_dialog_ok_normalizes(self):
        with mock.patch.object(n.messagebox, "showwarning"):
            dlg = n.LoginDialog(self.app, current=None)
            self.app.update_idletasks()
            dlg.value_var.set("Cookie: user_session=user_session_9_zz; a=1")
            dlg._on_ok()
        self.assertEqual(dlg.action, "ok")
        self.assertEqual(dlg.value, "user_session_9_zz")

    def test_dialog_rejects_non_session(self):
        with mock.patch.object(n.messagebox, "showwarning") as warn:
            dlg = n.LoginDialog(self.app, current=None)
            self.app.update_idletasks()
            dlg.value_var.set("https://example.com/whatever")
            dlg._on_ok()
            self.assertTrue(warn.called)
        self.assertIsNone(dlg.action)
        self.assertTrue(dlg.winfo_exists())   # 閉じずに再入力を促す
        dlg.destroy()

    def test_dialog_empty_ok_warns(self):
        with mock.patch.object(n.messagebox, "showwarning") as warn:
            dlg = n.LoginDialog(self.app, current=None)
            self.app.update_idletasks()
            dlg.value_var.set("   ")
            dlg._on_ok()
            self.assertTrue(warn.called)
        self.assertIsNone(dlg.action)
        self.assertTrue(dlg.winfo_exists())
        dlg.destroy()

    def test_dialog_clear(self):
        dlg = n.LoginDialog(self.app, current="user_session_1_ab")
        self.app.update_idletasks()
        dlg._on_clear()
        self.assertEqual(dlg.action, "clear")
        self.assertIsNone(dlg.value)

    def test_dialog_cancel(self):
        dlg = n.LoginDialog(self.app, current=None)
        self.app.update_idletasks()
        dlg._on_cancel()
        self.assertIsNone(dlg.action)
        self.assertIsNone(dlg.value)

    def test_dialog_escape_cancels(self):
        # 回帰テスト: Esc のバインドがハンドラを呼び忘れていないこと
        dlg = n.LoginDialog(self.app, current=None)
        self.app.update()
        dlg.focus_force()
        self.app.update()
        dlg.action = "sentinel"
        dlg.event_generate("<Escape>", when="now")
        self.app.update()
        self.assertIsNone(dlg.action)
        self.assertFalse(dlg.winfo_exists())

    def test_dialog_show_toggle(self):
        dlg = n.LoginDialog(self.app, current=None)
        self.app.update_idletasks()
        self.assertEqual(dlg.entry.cget("show"), "●")
        dlg.show_var.set(True)
        dlg._toggle_show()
        self.assertEqual(dlg.entry.cget("show"), "")
        dlg.destroy()

    # -- open_login_dialog の状態遷移 -------------------------------------
    def test_open_dialog_ok_sets_session(self):
        with mock.patch.object(n, "LoginDialog", return_value=_FakeDialog("ok", "user_session_1_ab")), \
                mock.patch.object(self.app, "wait_window"):
            self.app.open_login_dialog()
        self.assertEqual(self.app._session, "user_session_1_ab")

    def test_open_dialog_clear_unsets_session(self):
        self.app._session = "user_session_old"
        with mock.patch.object(n, "LoginDialog", return_value=_FakeDialog("clear")), \
                mock.patch.object(self.app, "wait_window"):
            self.app.open_login_dialog()
        self.assertIsNone(self.app._session)

    def test_open_dialog_cancel_keeps_state(self):
        self.app._session = "user_session_old"
        with mock.patch.object(n, "LoginDialog", return_value=_FakeDialog(None)), \
                mock.patch.object(self.app, "wait_window"):
            self.app.open_login_dialog()
        self.assertEqual(self.app._session, "user_session_old")

    def test_open_dialog_no_duplicate(self):
        existing = _FakeDialog()
        self.app._login_dlg = existing
        with mock.patch.object(n, "LoginDialog") as ctor:
            self.app.open_login_dialog()
        self.assertFalse(ctor.called)
        self.assertTrue(existing.lifted)

    # -- 状態ラベル --------------------------------------------------------
    def test_indicator_labels(self):
        cases = [
            (("v", "gui"), "設定済み（入力）"),
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
        with mock.patch.object(n, "resolve_session", return_value=("v", "gui")):
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

    # -- _ensure_session ---------------------------------------------------
    def test_ensure_session_returns_existing(self):
        with mock.patch.object(n, "resolve_session", return_value=("user_session_1_ab", "gui")):
            self.assertEqual(self.app._ensure_session(), "user_session_1_ab")

    def test_ensure_session_declined(self):
        with mock.patch.object(n, "resolve_session", return_value=(None, None)), \
                mock.patch.object(n.messagebox, "askyesno", return_value=False):
            self.assertIsNone(self.app._ensure_session())

    def test_ensure_session_via_dialog(self):
        # 呼び出し回数ではなく「状態」で検証する（リファクタに強い）
        def fake_resolve(gui_value):
            return (gui_value, "gui") if gui_value else (None, None)

        def fake_open():
            self.app._session = "user_session_1_ab"

        with mock.patch.object(n, "resolve_session", side_effect=fake_resolve), \
                mock.patch.object(n.messagebox, "askyesno", return_value=True), \
                mock.patch.object(self.app, "open_login_dialog", side_effect=fake_open):
            self.assertEqual(self.app._ensure_session(), "user_session_1_ab")


if __name__ == "__main__":
    unittest.main()
