"""Ozon Seller API Client-Id rate limiter (documented 50 rps)."""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from review_processor import ozon_fbs_rate_limit as rl
from review_processor.ozon_fbs import OzonFbsClient


class RateLimitConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        rl.reset_limiters_for_tests()

    def test_default_under_documented_ceiling(self) -> None:
        env = {
            k: v
            for k, v in __import__("os").environ.items()
            if k not in {"OZON_API_MAX_RPS", "OZON_API_RATE_LIMIT"}
        }
        with patch.dict("os.environ", env, clear=True):
            rate = rl.configured_max_rps()
        self.assertGreater(rate, 0)
        self.assertLessEqual(rate, rl.OZON_DOCUMENTED_MAX_RPS)
        self.assertEqual(rate, 40.0)

    def test_env_clamped_to_documented_max(self) -> None:
        with patch.dict("os.environ", {"OZON_API_MAX_RPS": "999"}, clear=False):
            self.assertEqual(rl.configured_max_rps(), 50.0)

    def test_disable_via_env(self) -> None:
        with patch.dict("os.environ", {"OZON_API_RATE_LIMIT": "off"}, clear=False):
            self.assertEqual(rl.configured_max_rps(), 0.0)


class TokenBucketTests(unittest.TestCase):
    def tearDown(self) -> None:
        rl.reset_limiters_for_tests()

    def test_bucket_paces_burst(self) -> None:
        bucket = rl.TokenBucketLimiter(rate=20.0)
        t0 = time.monotonic()
        for _ in range(25):
            bucket.acquire(1.0)
        elapsed = time.monotonic() - t0
        # 20 capacity free, then ~5 tokens need ~0.25s at 20/s.
        self.assertGreaterEqual(elapsed, 0.15)

    def test_shared_limiter_per_client(self) -> None:
        with patch.dict("os.environ", {"OZON_API_MAX_RPS": "30"}, clear=False):
            rl.reset_limiters_for_tests()
            a = rl.limiter_for_client("cid-1")
            b = rl.limiter_for_client("cid-1")
            c = rl.limiter_for_client("cid-2")
        self.assertIs(a, b)
        self.assertIsNot(a, c)


class RetryAfterTests(unittest.TestCase):
    def test_parse_retry_after(self) -> None:
        headers = {"Retry-After": "2"}
        self.assertEqual(rl.parse_retry_after_seconds(headers), 2.0)

    def test_backoff_prefers_header(self) -> None:
        self.assertEqual(
            rl.backoff_seconds_for_429(attempt=0, retry_after=3.5),
            3.5,
        )

    def test_backoff_exponential_without_header(self) -> None:
        self.assertEqual(rl.backoff_seconds_for_429(attempt=0, retry_after=None), 0.5)
        self.assertEqual(rl.backoff_seconds_for_429(attempt=1, retry_after=None), 1.0)
        self.assertEqual(rl.backoff_seconds_for_429(attempt=2, retry_after=None), 2.0)


class Client429RetryTests(unittest.TestCase):
    def tearDown(self) -> None:
        rl.reset_limiters_for_tests()

    def test_post_json_retries_429_then_succeeds(self) -> None:
        client = OzonFbsClient("cid", "key")
        fp = MagicMock()
        fp.read.return_value = b"rate"
        real_http = HTTPError(
            url="https://api-seller.ozon.ru/x",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "0"},
            fp=fp,
        )

        ok = MagicMock()
        ok.read.return_value = b'{"result":{"ok":true}}'
        ok.__enter__.return_value = ok
        ok.__exit__.return_value = False

        with (
            patch.dict("os.environ", {"OZON_API_RATE_LIMIT": "off"}, clear=False),
            patch("review_processor.ozon_fbs.urlopen") as urlopen_mock,
            patch("review_processor.ozon_fbs.time.sleep") as sleep_mock,
        ):
            urlopen_mock.side_effect = [real_http, ok]
            out = client.post_json("/v3/posting/fbs/get", {"posting_number": "1"})
        self.assertEqual(out, {"result": {"ok": True}})
        self.assertEqual(urlopen_mock.call_count, 2)
        sleep_mock.assert_called()


if __name__ == "__main__":
    unittest.main()
