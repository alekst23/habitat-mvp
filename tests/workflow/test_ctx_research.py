import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("research", ROOT / "scripts/ctx_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


class ResearchTests(unittest.TestCase):
    def test_runner_has_exact_documentation_hosts_without_wildcard_egress(self):
        config = yaml.safe_load((ROOT / ".gitlab/duo/agent-config.yml").read_text())["network_policy"]
        self.assertTrue(set(research.DOCS) <= set(config["allowed_domains"]))
        self.assertFalse(config["allow_all_unix_sockets"])
        self.assertFalse(any("*" in host for host in config["allowed_domains"]))

    def test_only_public_docs_not_provider_operations_or_exfiltration(self):
        self.assertEqual(research.checked_url("https://developer.paypal.com/docs/api/orders/v2/#authorization"),
                         "https://developer.paypal.com/docs/api/orders/v2/")
        for url in ("http://render.com/docs/foo", "https://render.com/v1/services",
                    "https://api-m.paypal.com/v2/checkout/orders", "https://localhost/docs/a",
                    "https://user:secret@render.com/docs/a", "https://render.com:443/docs/a",
                    "https://render.com.evil.test/docs/a", "https://render.com/docs/a?secret=x",
                    "https://render.com/docs/%2e%2e/v1/services", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                research.checked_url(url)

    def test_private_resolution_and_redirects_are_rejected(self):
        with patch.object(research.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(ValueError): research.public_host("https://render.com/docs/foo")
        request = research.Request("https://render.com/docs/foo")
        with self.assertRaises(ValueError):
            research.DocsRedirect().redirect_request(request, None, 302, "", {}, "https://evil.test/foo")

    def test_text_extraction_does_not_execute_or_include_scripts(self):
        parser = research.VisibleText()
        parser.feed("<h1>Limits</h1><script>steal()</script><p>Read the current limit.</p>")
        self.assertEqual(parser.parts, ["Limits", "Read the current limit."])


if __name__ == "__main__":
    unittest.main()
