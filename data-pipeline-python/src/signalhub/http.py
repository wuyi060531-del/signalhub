"""有限重试、大小上限、禁止重定向、DNS 解析后固定 IP（防重绑定）。"""
import ipaddress
import socket
import time
import random
from contextlib import closing
from urllib.parse import urlsplit
import httpx

from .diagnostics import SourceAccessError

MAX_BYTES = 32 * 1024 * 1024

def public_address(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise SourceAccessError('外部采集只接受无凭据、443 端口的 HTTPS URL')
    addresses = [x[4][0] for x in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)]
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
        raise SourceAccessError('禁止访问本机、私网、保留地址')
    return p.hostname, addresses[0]

class Fetcher:
    def __init__(self, client=None, sleep=time.sleep, attempts=3):
        self.client = client or httpx.Client(timeout=20, follow_redirects=False, trust_env=False)
        self.sleep, self.attempts = sleep, attempts
        self.pinned = client is None

    def get(self, url, headers=None):
        host, address = public_address(url)
        for attempt in range(self.attempts):
            try:
                request = self.client.build_request('GET', url, headers=headers or {})
                if self.pinned:
                    request.url = request.url.copy_with(host=address)
                    request.headers['Host'] = host
                    request.extensions['sni_hostname'] = host
                with closing(self.client.send(request, stream=True)) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == self.attempts - 1: response.raise_for_status()
                        delay = response.headers.get('Retry-After', '')
                        self.sleep(min(float(delay),30) if delay.isdigit() else min(2**attempt + random.random(),10))
                        continue
                    if response.status_code not in (200,304): response.raise_for_status()
                    chunks, total = [], 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_BYTES: raise ValueError('响应超过 32MB 上限')
                        chunks.append(chunk)
                    # iter_bytes 已解压；避免新 Response 再按 content-encoding 解压一次。
                    decoded_headers = {k:v for k,v in response.headers.items() if k.lower() not in ('content-encoding','content-length')}
                    return httpx.Response(response.status_code, headers=decoded_headers, content=b''.join(chunks), request=request)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self.attempts - 1: raise
                self.sleep(min(2**attempt,10))
        raise RuntimeError('请求失败')
