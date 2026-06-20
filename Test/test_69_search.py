from curl_cffi import requests
from bs4 import BeautifulSoup
import urllib.parse
query = "大奉打更人".encode('gbk')
data = b'searchkey=' + urllib.parse.quote(query).encode('ascii') + b'&searchtype=all'
url = "https://www.69shuba.cx/modules/article/search.php"
headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.post(url, headers=headers, data=data, impersonate="chrome110", timeout=15)
r.encoding = 'gbk'
print("URL:", r.url)
soup = BeautifulSoup(r.text, 'html.parser')
for h3 in soup.select('h3'):
    a = h3.select_one('a')
    if a: print("Found:", a.text, a.get('href'))
for div in soup.select('.newnav h3 a'):
    print("Found:", div.text, div.get('href'))
