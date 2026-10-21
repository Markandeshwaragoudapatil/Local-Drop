"""Integration tests for LocalDrop's HTTP server using only the standard library."""

from __future__ import annotations

import http.cookiejar
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from localdrop import server as localdrop_server


class QuietHandler(localdrop_server.LocalDropHandler):
    """Keep expected HTTP requests quiet while exercising the real handler."""

    def log_message(self, fmt: str, *args: object) -> None:
        pass


class TestThreadingHTTPServer(ThreadingHTTPServer):
    """Allow enough queued connections for the concurrent-client test."""

    request_queue_size = 32


class LocalDropHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp_dir.name)
        self.share_dir = self.temp_root / "ShareFiles"
        self.share_dir.mkdir()
        (self.temp_root / "outside-secret.txt").write_text("not shared", encoding="utf-8")

        self.original_share_dir = localdrop_server.SHARE_DIR
        self.original_pin = localdrop_server.SERVER_PIN
        self.original_max_upload_bytes = localdrop_server.MAX_UPLOAD_BYTES
        self.original_sessions = localdrop_server.SESSIONS.copy()
        self.original_pin_failures = localdrop_server.PIN_FAILURES.copy()

        localdrop_server.SHARE_DIR = self.share_dir
        localdrop_server.SERVER_PIN = "1234"
        localdrop_server.SESSIONS.clear()
        localdrop_server.PIN_FAILURES.clear()

        self.httpd = TestThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.httpd.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.server_thread = threading.Thread(
            target=self.httpd.serve_forever, name="localdrop-test-server", daemon=True
        )
        self.server_thread.start()
        self.opener = self.make_opener()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server_thread.join(timeout=3)
        localdrop_server.SHARE_DIR = self.original_share_dir
        localdrop_server.SERVER_PIN = self.original_pin
        localdrop_server.MAX_UPLOAD_BYTES = self.original_max_upload_bytes
        localdrop_server.SESSIONS.clear()
        localdrop_server.SESSIONS.update(self.original_sessions)
        localdrop_server.PIN_FAILURES.clear()
        localdrop_server.PIN_FAILURES.update(self.original_pin_failures)
        self.temp_dir.cleanup()

    @staticmethod
    def make_opener() -> urllib.request.OpenerDirector:
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(
        self,
        path: str,
        *,
        opener: urllib.request.OpenerDirector | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ):
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers or {}
        )
        return (opener or self.opener).open(req, timeout=10)

    def login(
        self, opener: urllib.request.OpenerDirector | None = None, pin: str = "1234"
    ) -> str:
        body = urllib.parse.urlencode({"pin": pin}).encode("utf-8")
        with self.request(
            "/login",
            opener=opener,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            return response.read().decode("utf-8", errors="replace")

    @staticmethod
    def multipart(files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
        boundary = "----LocalDropUnitTestBoundary"
        marker = boundary.encode("ascii")
        chunks: list[bytes] = []
        for filename, data in files:
            chunks.extend(
                [
                    b"--" + marker + b"\r\n",
                    (
                        'Content-Disposition: form-data; name="files"; filename="'
                        + filename.replace('"', "")
                        + '"\r\n'
                    ).encode("utf-8"),
                    b"Content-Type: application/octet-stream\r\n\r\n",
                    data,
                    b"\r\n",
                ]
            )
        chunks.append(b"--" + marker + b"--\r\n")
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def upload(
        self,
        files: list[tuple[str, bytes]],
        opener: urllib.request.OpenerDirector | None = None,
    ):
        body, content_type = self.multipart(files)
        return self.request(
            "/upload",
            opener=opener,
            data=body,
            headers={"Content-Type": content_type},
        )

    def post_form(
        self,
        path: str,
        values: dict[str, str],
        opener: urllib.request.OpenerDirector | None = None,
    ):
        body = urllib.parse.urlencode(values).encode("utf-8")
        return self.request(
            path,
            opener=opener,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    def test_authentication_requires_pin_and_creates_session(self) -> None:
        with self.request("/") as response:
            page = response.read().decode("utf-8")
        self.assertIn("Unlock LocalDrop", page)

        (self.share_dir / "private.txt").write_text("hello", encoding="utf-8")
        # Protected file listing remains unavailable until a valid PIN is submitted.
        with self.request("/") as response:
            unauthenticated_page = response.read().decode("utf-8")
        self.assertIn("Unlock LocalDrop", unauthenticated_page)
        self.assertNotIn("private.txt", unauthenticated_page)

        self.login()
        with self.request("/") as response:
            authenticated_page = response.read().decode("utf-8")
        self.assertIn("private.txt", authenticated_page)

        jar = next(
            handler.cookiejar
            for handler in self.opener.handlers
            if isinstance(handler, urllib.request.HTTPCookieProcessor)
        )
        session_cookie = next(
            cookie for cookie in jar if cookie.name == "localdrop_session"
        )
        self.assertTrue(session_cookie.value)
        self.assertTrue(
            any(session_cookie.has_nonstandard_attr(name) for name in ("HttpOnly", "httponly"))
        )
        same_site = next(
            (
                session_cookie.get_nonstandard_attr(name)
                for name in ("SameSite", "samesite")
                if session_cookie.has_nonstandard_attr(name)
            ),
            None,
        )
        self.assertEqual(same_site, "Strict")

    def test_repeated_wrong_pin_attempts_trigger_cooldown(self) -> None:
        for _ in range(localdrop_server.MAX_PIN_FAILURES):
            page = self.login(pin="9999")
        self.assertIn("Too many incorrect attempts", page)
        self.assertGreater(localdrop_server.pin_cooldown_remaining("127.0.0.1"), 0)

    def test_path_traversal_cannot_read_file_outside_shared_folder(self) -> None:
        self.login()
        traversal = urllib.parse.quote("../outside-secret.txt", safe="")
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request(f"/download?file={traversal}")
        self.assertEqual(context.exception.code, 404)
        self.assertEqual(
            (self.temp_root / "outside-secret.txt").read_text(encoding="utf-8"),
            "not shared",
        )

    def test_filename_collision_preserves_existing_file(self) -> None:
        self.login()
        with self.upload([("report.txt", b"first")]) as response:
            self.assertEqual(response.status, 200)
        with self.upload([("report.txt", b"second")]) as response:
            self.assertEqual(response.status, 200)

        self.assertEqual((self.share_dir / "report.txt").read_bytes(), b"first")
        self.assertEqual((self.share_dir / "report (1).txt").read_bytes(), b"second")

    def test_configured_upload_limit_is_exactly_100_mib(self) -> None:
        self.assertEqual(localdrop_server.MAX_UPLOAD_BYTES, 100 * 1024 * 1024)

    def test_upload_payload_over_100_mib_limit_is_rejected(self) -> None:
        self.login()
        # Use a small test limit to verify the real byte-count check without allocating 100 MiB.
        localdrop_server.MAX_UPLOAD_BYTES = 32
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.upload([("first.bin", b"x" * 20), ("second.bin", b"y" * 13)])
        self.assertEqual(context.exception.code, 413)
        self.assertFalse((self.share_dir / "first.bin").exists())
        self.assertFalse((self.share_dir / "second.bin").exists())

    def test_upload_at_limit_is_accepted(self) -> None:
        self.login()
        localdrop_server.MAX_UPLOAD_BYTES = 32
        with self.upload([("at-limit.bin", b"x" * 32)]) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual((self.share_dir / "at-limit.bin").read_bytes(), b"x" * 32)

    def test_delete_removes_file_inside_shared_folder(self) -> None:
        self.login()
        target = self.share_dir / "delete-me.txt"
        target.write_text("delete this", encoding="utf-8")
        with self.post_form("/delete", {"file": "delete-me.txt"}) as response:
            page = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
        self.assertIn("Deleted delete-me.txt", page)
        self.assertFalse(target.exists())

    def test_delete_rejects_path_traversal(self) -> None:
        self.login()
        with self.post_form("/delete", {"file": "../outside-secret.txt"}) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(
            (self.temp_root / "outside-secret.txt").read_text(encoding="utf-8"),
            "not shared",
        )

    def test_shutdown_requires_correct_pin_and_schedules_stop(self) -> None:
        self.login()
        with mock.patch.object(localdrop_server.threading, "Timer") as timer_mock:
            with self.post_form(
                "/shutdown", {"confirm": "yes", "pin": "9999"}
            ) as response:
                page = response.read().decode("utf-8")
            self.assertIn("server is still running", page)
            timer_mock.assert_not_called()

            with self.post_form(
                "/shutdown", {"confirm": "yes", "pin": "1234"}
            ) as response:
                page = response.read().decode("utf-8")
            self.assertIn("LocalDrop is stopping", page)
            timer_mock.assert_called_once()
            self.assertEqual(timer_mock.call_args.args[0], 2.0)
            timer_mock.return_value.start.assert_called_once()

    def test_unauthenticated_delete_does_not_delete_file(self) -> None:
        target = self.share_dir / "keep.txt"
        target.write_text("keep", encoding="utf-8")
        no_session_opener = self.make_opener()
        with self.post_form(
            "/delete", {"file": "keep.txt"}, opener=no_session_opener
        ) as response:
            page = response.read().decode("utf-8")
        self.assertIn("Unlock LocalDrop", page)
        self.assertTrue(target.exists())

    def test_multiple_simultaneous_clients_do_not_overwrite_same_filename(self) -> None:
        client_count = 8

        def worker(index: int) -> tuple[int, bytes]:
            opener = self.make_opener()
            self.login(opener=opener)
            payload = f"client-{index}".encode("ascii")
            with self.upload([("parallel.txt", payload)], opener=opener) as response:
                self.assertEqual(response.status, 200)
            return index, payload

        with ThreadPoolExecutor(max_workers=client_count) as pool:
            expected = list(pool.map(worker, range(client_count)))

        files = list(self.share_dir.glob("parallel*.txt"))
        self.assertEqual(len(files), client_count)
        self.assertEqual({path.read_bytes() for path in files}, {payload for _, payload in expected})


if __name__ == "__main__":
    unittest.main()
