import os
import urllib.parse

import pytest
from bs4 import BeautifulSoup
from curl_cffi import requests


@pytest.mark.skipif(os.getenv("RUN_NETWORK_TESTS") != "1", reason="network integration test disabled")
def test_69shuba_search_integration():
    query = "大奉打更人".encode("gbk")
    data = b"searchkey=" + urllib.parse.quote(query).encode("ascii") + b"&searchtype=all"
    url = "https://www.69shuba.cx/modules/article/search.php"
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.post(url, headers=headers, data=data, impersonate="chrome110", timeout=15)
    response.encoding = "gbk"
    soup = BeautifulSoup(response.text, "html.parser")
    results = [a for a in soup.select("h3 a, .newnav h3 a") if a.get_text(strip=True)]

    assert response.status_code < 500
    assert results
