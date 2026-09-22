"""Site-specific bypass adapters.

Design notes
------------
vplink.in / arolinks.com / gplinks / droplink all belong to the "safelink
script" family: the short URL sets session cookies (AppSession, ref<code>,
gt_uc_ …), bounces through an intermediate blog/timer page, and the final
destination is released by submitting a hidden form (usually to /links/go)
with the session cookies attached. The generic `safelink_walk` below
replays that whole chain automatically.

curl_cffi with Chrome impersonation is used because these sites sit behind
Cloudflare and plain `requests` gets TLS-fingerprint blocked.

Known limitation: both vplink.in and arolinks.com run a VPN/proxy check
(checkVPNStatus) — datacenter IPs (incl. Render) may occasionally be served
the "disable VPN" interstitial instead of the real page. Retry usually helps.
"""
import base64
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as creq

log = logging.getLogger("bypassbot.adapters")

TIMEOUT = 30
MAX_HOPS = 6
GO_ACTION = re.compile(r"(/links/go|/go\b|go\.php|get-?link|continue)", re.I)
JS_REDIRECT = [
    re.compile(r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)', re.I),
    re.compile(r'location\.replace\(\s*["\']([^"\']+)["\']', re.I),
    re.compile(r'window\.open\(\s*["\']([^"\']+)["\']', re.I),
]
AD_HOSTS = (
    "doubleclick", "googleads", "googlesyndication", "adnxs", "adservice",
    "facebook.com", "analytics", "track", "clickcease", "cloudflare",
)


def new_session():
    # Chrome TLS fingerprint impersonation — required for Cloudflare-fronted sites
    return creq.Session(impersonate="chrome", timeout=TIMEOUT)


def _host(u: str) -> str:
    return urlparse(u).netloc.lower().removeprefix("www.")


def _is_ad(u: str) -> bool:
    return any(b in u.lower() for b in AD_HOSTS)


def _find_destination(html: str, current_host: str) -> str | None:
    """Look for an external destination link in the page."""
    soup = BeautifulSoup(html, "lxml")
    # 1) anchors clearly marked as the "get link" / nofollow destination
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        h = _host(href)
        if not h or h == current_host or h.endswith("." + current_host):
            continue
        cls = " ".join(a.get("class", [])) + " " + (a.get("id") or "")
        rel = " ".join(a.get("rel", []))
        if ("nofollow" in rel or GO_ACTION.search(cls) or "btn" in cls) and not _is_ad(href):
            return href
    # 2) JS-assigned external URLs
    for pat in JS_REDIRECT:
        for m in pat.finditer(html):
            u = m.group(1)
            if u.startswith("http") and _host(u) != current_host and not _is_ad(u):
                return u
    return None


def _js_next(html: str, current_url: str) -> str | None:
    """Extract the next hop from JS redirects / meta refresh (same-site hops)."""
    for pat in JS_REDIRECT:
        m = pat.search(html)
        if m:
            u = m.group(1)
            if u.startswith("/"):
                return urljoin(current_url, u)
            if u.startswith("http"):
                return u
    m = re.search(r'url\s*=\s*["\']?(https?://[^"\'>\s]+)', html, re.I)  # meta refresh
    if m:
        return m.group(1)
    return None


def _submit_go_form(session, html: str, page_url: str):
    """Submit the page's go/continue form; returns (next_url, html) or None."""
    soup = BeautifulSoup(html, "lxml")
    forms = soup.find_all("form")
    forms = [f for f in forms if GO_ACTION.search(f.get("action") or "")] or forms[-1:]
    for f in forms:
        data = {i.get("name"): i.get("value", "") for i in f.find_all("input") if i.get("name")}
        action = urljoin(page_url, f.get("action") or page_url)
        method = (f.get("method") or "get").lower()
        log.info("submitting form (%s) -> %s fields=%s", method, action, list(data))
        resp = session.post(action, data=data, allow_redirects=True) if method == "post" \
            else session.get(action, params=data, allow_redirects=True)
        return str(resp.url), resp.text
    return None


def safelink_walk(url: str) -> str:
    """Generic walker for safelink-family sites (vplink.in, arolinks.com, ...)."""
    s = new_session()
    current = url
    for hop in range(MAX_HOPS):
        r = s.get(current, allow_redirects=True)
        html, page_url = r.text, str(r.url)
        log.info("hop %d: %s", hop, page_url)

        dest = _find_destination(html, _host(page_url))
        if dest:
            return dest

        hop_result = _submit_go_form(s, html, page_url)
        if hop_result:
            next_url, next_html = hop_result
            dest = _find_destination(next_html, _host(next_url))
            if dest:
                return dest
            if _host(next_url) != _host(page_url):
                return next_url  # form threw us off-site = that IS the destination
            current = next_url
            continue

        nxt = _js_next(html, page_url)
        if nxt and nxt != current:
            if _host(nxt) != _host(page_url) and not _is_ad(nxt):
                return nxt
            current = nxt
            continue

        break
    raise ValueError(
        "Walked the safelink chain but found no destination. "
        "The site may have added a timed JS gate, VPN check, or captcha "
        "that needs a site-specific update."
    )


def linkvertise(url: str) -> str:
    """Best-effort linkvertise: target is often embedded as JSON/base64 in the page."""
    s = new_session()
    r = s.get(url)
    m = re.search(r'"target"\s*:\s*"(https?:[^"\\]+)', r.text)
    if m:
        return m.group(1)
    m = re.search(r'data-target=["\']([A-Za-z0-9+/=]{20,})["\']', r.text)
    if m:
        try:
            return base64.b64decode(m.group(1)).decode()
        except Exception:
            pass
    raise ValueError("linkvertise layout changed — this adapter needs a site-specific update.")


# (domain list, adapter) — checked in order by resolver.resolve_link
SAFELINK_FAMILY = [
    "vplink.in", "arolinks.com", "gplinks.co", "gplinks.in", "droplink.co",
    "tnshort.net", "rslinks.net", "xpshort.com", "earnl.xyz", "mplaylink.com",
    "adrinolinks.in", "krownlinks.me", "du-link.in", "onepagelink.in",
]

ADAPTERS = [
    (SAFELINK_FAMILY, safelink_walk),
    (["linkvertise.com", "link-to.net", "direct-link.net", "up-to-down.net"], linkvertise),
]
