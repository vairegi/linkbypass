"""Site-specific bypass adapters.

vplink.in / arolinks.com and siblings belong to the "safelink script" family:
the short URL sets session cookies (AppSession, ref<code>, gt_uc_ …), the page
then runs an in-browser VPN/proxy check (checkVPNStatus), and ONLY after that
passes does JavaScript render the timer page and the final /links/go form.

Two-layer strategy:
1. safelink_walk  — fast pure-HTTP replay (works when the VPN check passes
                    server-side or is absent).
2. browser_bypass — real Chromium via Playwright; executes the JS so the VPN
                    check runs "in browser" and the final form becomes visible.

Both honor the PROXY_URL env var (e.g. http://user:pass@residential-proxy:port)
— the proper fix when the VPN check blocks datacenter IPs like Render's.
curl_cffi Chrome impersonation is used because these sites sit behind Cloudflare.
"""
import base64
import logging
import os
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as creq

log = logging.getLogger("bypassbot.adapters")

TIMEOUT = 30
MAX_HOPS = 6
PROXY_URL = os.environ.get("PROXY_URL")  # optional: http://user:pass@host:port
BROWSER_SITES = ("vplink.in", "arolinks.com")  # VPN-gated: prefer real browser

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
    kwargs = {"impersonate": "chrome", "timeout": TIMEOUT}
    if PROXY_URL:
        kwargs["proxy"] = PROXY_URL
    return creq.Session(**kwargs)


def _host(u: str) -> str:
    return urlparse(u).netloc.lower().removeprefix("www.")


def _is_ad(u: str) -> bool:
    return any(b in u.lower() for b in AD_HOSTS)


def _find_destination(html: str, current_host: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
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
    for pat in JS_REDIRECT:
        for m in pat.finditer(html):
            u = m.group(1)
            if u.startswith("http") and _host(u) != current_host and not _is_ad(u):
                return u
    return None


def _js_next(html: str, current_url: str) -> str | None:
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
    """Pure-HTTP walker for safelink-family sites (works when VPN check is absent/lenient)."""
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
        "The site is serving a JS/VPN-check shell page (no form). "
        "A browser bypass or residential proxy is needed."
    )


def browser_bypass(url: str) -> str:
    """Real-Chromium bypass: runs the site's JS so the VPN check + timer execute,
    then extracts the destination from the fully-rendered page or by clicking
    the final /links/go form."""
    from playwright.sync_api import sync_playwright  # imported lazily

    proxy = {"server": PROXY_URL} if PROXY_URL else None
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy=proxy,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)  # let the VPN check + first JS pass

            for step in range(8):
                # Already landed off-site? Done.
                if _host(page.url) != _host(url) and not _is_ad(page.url):
                    return page.url

                html = page.content()
                dest = _find_destination(html, _host(page.url))
                if dest:
                    return dest

                # Try to click the "get link / continue" button or submit go-form
                clicked = page.evaluate(
                    """() => {
                        const sels = [
                          'form[action*="/links/go"] button[type=submit]',
                          'form[action*="/links/go"] input[type=submit]',
                          'button.btn', 'a.btn', '#getlink', '.get-link',
                          'a[rel=nofollow]'
                        ];
                        for (const s of sels) {
                          const el = document.querySelector(s);
                          if (el) { el.click(); return s; }
                        }
                        const f = document.querySelector('form[action*="/links/go"]');
                        if (f) { f.submit(); return 'form-submit'; }
                        return null;
                    }"""
                )
                log.info("browser step %d: clicked=%s url=%s", step, clicked, page.url)
                page.wait_for_timeout(4000)  # wait out the timer between steps

            html = page.content()
            dest = _find_destination(html, _host(page.url))
            if dest:
                return dest
            if _host(page.url) != _host(url) and not _is_ad(page.url):
                return page.url
            raise ValueError(
                "Browser bypass walked the chain but no destination appeared "
                "(site may require a residential IP — set PROXY_URL)."
            )
        finally:
            browser.close()


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
    "gplinks.co", "gplinks.in", "droplink.co", "tnshort.net", "rslinks.net",
    "xpshort.com", "earnl.xyz", "mplaylink.com", "adrinolinks.in",
    "krownlinks.me", "du-link.in", "onepagelink.in",
]

ADAPTERS = [
    (BROWSER_SITES, browser_bypass),      # vplink.in / arolinks.com — VPN-gated
    (SAFELINK_FAMILY, safelink_walk),     # other safelink sites — fast HTTP path
    (["linkvertise.com", "link-to.net", "direct-link.net", "up-to-down.net"], linkvertise),
]
