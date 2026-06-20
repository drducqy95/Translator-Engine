from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
query = "大奉打更人 site:69shuba.cx"
url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.get(url, headers=headers, impersonate="chrome110")
soup = BeautifulSoup(r.text, 'html.parser')
for a in soup.select('a.result__url'):
    print(a.get('href'))
