from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_trend_source.py"

spec = importlib.util.spec_from_file_location("build_trend_source", SCRIPT)
bts = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(bts)


def write_fixture(fixtures: Path, url: str, body: str) -> None:
    (fixtures / bts.fixture_name(url)).write_text(body, encoding="utf-8")


def rss(title: str = "RSS AI workflow") -> str:
    return f"""<?xml version="1.0"?>
<rss><channel><item>
  <title>{title}</title>
  <link>https://example.com/rss-ai</link>
  <description><![CDATA[<p>AI workflow summary</p>]]></description>
  <pubDate>Tue, 16 Jun 2026 08:30:00 GMT</pubDate>
</item></channel></rss>"""


def google_rss() -> str:
    return rss("SpaceX IPO aims for AI infrastructure")


def github_payload() -> str:
    return json.dumps({
        "items": [{
            "full_name": "servagent-ai/example-agent",
            "html_url": "https://github.com/servagent-ai/example-agent",
            "description": "Example AI agent repository",
            "stargazers_count": 1200,
            "forks_count": 77,
            "pushed_at": "2026-06-16T08:00:00Z",
        }]
    })


def hn_payload() -> str:
    return json.dumps({
        "hits": [{
            "title": "Show HN: AI workflow automation",
            "url": "https://news.ycombinator.com/item?id=1",
            "story_text": "Automation story",
            "points": 180,
            "num_comments": 31,
            "created_at_i": 1781596800,
            "objectID": "1",
        }]
    })


class UnitTests(unittest.TestCase):
    def test_clean_html_compacts_text(self):
        self.assertEqual(bts.clean_html("<p>Hello&nbsp;</p> <b>AI</b>"), "Hello&nbsp; AI")

    def test_make_row_rejects_empty_title(self):
        self.assertIsNone(bts.make_row("", "https://example.com", "", "rss", 1, 1, 1, "rss"))

    def test_dedupe_keeps_hottest_duplicate(self):
        items = [
            bts.make_row("Same", "https://example.com/a", "", "rss", 1, 1, 1, "rss"),
            bts.make_row("Same", "https://example.com/a", "", "rss", 9, 1, 1, "rss"),
        ]
        rows = bts.dedupe(items)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hot"], 9)


class ContractTests(unittest.TestCase):
    def test_validate_payload_requires_adapter_contract(self):
        good = {
            "generated_at": 1781596800,
            "items": [bts.make_row("A", "https://example.com/a", "s", "rss", 1, 2, 3, "rss")],
        }
        bts.validate_payload(good)

        bad = {"generated_at": 1781596800, "items": [{"title": "A"}]}
        with self.assertRaisesRegex(ValueError, "missing required keys"):
            bts.validate_payload(bad)

    def test_public_config_does_not_point_at_personal_state(self):
        text = (ROOT / "config" / "sources.json").read_text(encoding="utf-8")
        forbidden = ["/Users/", "cookies/", "TOKEN", "SECRET", "PRIVATE"]
        self.assertFalse([needle for needle in forbidden if needle in text])


class ModuleEndToEndTests(unittest.TestCase):
    def test_build_payload_covers_each_configured_source_category(self):
        cfg = {
            "google_news_queries": ["SpaceX IPO AI infrastructure"],
            "rss": [{"id": "techcrunch", "url": "https://example.com/rss.xml"}],
            "github_queries": ["topic:ai-agent stars:>500"],
            "hackernews_queries": ["AI workflow"],
        }

        def fake_http_get(url: str, headers=None):
            if "news.google.com" in url:
                return google_rss()
            if "api.github.com/search/repositories" in url:
                return github_payload()
            if "hn.algolia.com" in url:
                return hn_payload()
            if url == "https://example.com/rss.xml":
                return rss()
            raise AssertionError(f"unexpected url: {url}")

        with mock.patch.object(bts, "http_get", side_effect=fake_http_get):
            payload = bts.build_payload(cfg)

        categories = {item.get("source_category") for item in payload["items"]}
        self.assertEqual(categories, {"google_news", "rss", "github", "hackernews"})
        self.assertTrue(any("SpaceX IPO" in item["title"] for item in payload["items"]))


class FunctionalEndToEndTests(unittest.TestCase):
    def test_script_writes_valid_public_json_from_fixtures(self):
        with tempfile.TemporaryDirectory(prefix="zhibo_trend_source_") as td:
            root = Path(td)
            fixtures = root / "fixtures"
            fixtures.mkdir()
            cfg = {
                "google_news_queries": ["SpaceX IPO AI infrastructure"],
                "rss": [{"id": "techcrunch", "url": "https://example.com/rss.xml"}],
                "github_queries": ["topic:ai-agent stars:>500"],
                "hackernews_queries": ["AI workflow"],
            }
            config = root / "sources.json"
            output = root / "trendradar_source.json"
            config.write_text(json.dumps(cfg), encoding="utf-8")

            write_fixture(
                fixtures,
                "https://news.google.com/rss/search?q=SpaceX%20IPO%20AI%20infrastructure&hl=en-US&gl=US&ceid=US:en",
                google_rss(),
            )
            write_fixture(fixtures, "https://example.com/rss.xml", rss())
            write_fixture(
                fixtures,
                "https://api.github.com/search/repositories?q=topic%3Aai-agent%20stars%3A%3E500&sort=stars&order=desc&per_page=30",
                github_payload(),
            )
            write_fixture(
                fixtures,
                "https://hn.algolia.com/api/v1/search?tags=story&query=AI%20workflow&hitsPerPage=30",
                hn_payload(),
            )

            env = {
                **os.environ,
                "TREND_SOURCE_CONFIG": str(config),
                "TREND_SOURCE_OUT": str(output),
                "TREND_SOURCE_FIXTURE_DIR": str(fixtures),
            }
            subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, env=env, check=True)
            payload = json.loads(output.read_text(encoding="utf-8"))

        bts.validate_payload(payload)
        self.assertGreaterEqual(len(payload["items"]), 4)
        self.assertIn("source_category", payload["items"][0])


if __name__ == "__main__":
    unittest.main()
