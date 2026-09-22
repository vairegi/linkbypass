"""Entry point for link resolution: route to a site adapter or generic resolver."""
import re
from urllib.parse import urlparse

from adapters import ADAPTERS, new_session


def generic_resolve(url: str) -> str:
    """Follow plain HTTP redirect chains; handles meta-refresh pages too."""
    s = new_session()
    r = s.get(url, allow_redirects=True)
    final = str(r.url)
    if final.rstrip("/") != url.rstrip("/"):
        return final
    m = re.search(r'url\s*=\s*["\']?(https?://[^"\'>\s]+)', r.text, re.I)  # meta refresh
    if m:
        return m.group(1)
    raise ValueError("Link did not redirect and no destination was found on the page.")


def resolve_link(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for domains, fn in ADAPTERS:
        if any(host == d or host.endswith("." + d) for d in domains):
            return fn(url)
    return generic_resolve(url)
