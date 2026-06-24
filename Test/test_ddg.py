import os
import urllib.parse

import pytest
from bs4 import BeautifulSoup
from curl_cffi import requests


@pytest.mark.skipif(os.getenv("RUN_NETWORK_TESTS") != "1", reason="network integration test disabled")
def test_duckduckgo_html_search_integration():
    query = "大奉打更人 site:69shuba.cx"
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(url, headers=headers, impersonate="chrome110", timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    assert response.status_code < 500
    assert soup.select("a.result__url")
