from __future__ import annotations

import html
import importlib
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


PLAYWRIGHT_INSTALL_HINT = (
    "Playwright runtime is unavailable; install the Python package and browser binaries with "
    "`python3 -m pip install playwright` and `python3 -m playwright install chromium`."
)
DEFAULT_DDG_HTML_URL_TEMPLATE = "https://html.duckduckgo.com/html/?q={query}"
DEFAULT_DDG_LITE_URL_TEMPLATE = "https://lite.duckduckgo.com/lite/?q={query}"
DEFAULT_BROWSER_SEARCH_URL_TEMPLATE = "https://duckduckgo.com/?q={query}&ia=web"
DEFAULT_NAVIGATION_TIMEOUT_MS = 15000
DEFAULT_TEXT_LIMIT = 8000


class PlaywrightRuntimeError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class SearchRuntimeError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.payload = dict(payload or {})


@dataclass(frozen=True)
class PlaywrightProbeResult:
    available: bool
    error_code: str | None = None
    reason: str | None = None


def probe_playwright_runtime() -> PlaywrightProbeResult:
    try:
        sync_api = importlib.import_module("playwright.sync_api")
    except Exception:
        return PlaywrightProbeResult(
            available=False,
            error_code="E_WEB_RUNTIME_UNAVAILABLE",
            reason=PLAYWRIGHT_INSTALL_HINT,
        )

    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        return PlaywrightProbeResult(
            available=False,
            error_code="E_WEB_RUNTIME_UNAVAILABLE",
            reason=f"{PLAYWRIGHT_INSTALL_HINT} detail={str(exc)[:240]}",
        )
    return PlaywrightProbeResult(available=True)


def duckduckgo_html_search(
    *,
    query: str,
    limit: int,
    include_metadata: bool = False,
) -> tuple[str, list[dict[str, Any]]] | dict[str, Any]:
    payload = duckduckgo_http_search(query=query, limit=limit)
    if include_metadata:
        return payload
    return payload["provider_used"], payload["results"]


def duckduckgo_http_search(*, query: str, limit: int) -> dict[str, Any]:
    encoded_query = urllib.parse.quote_plus(str(query or "").strip())
    attempts: list[dict[str, Any]] = []
    last_error: SearchRuntimeError | None = None
    last_page: dict[str, str] | None = None
    for variant, template in (
        ("html", DEFAULT_DDG_HTML_URL_TEMPLATE),
        ("lite", DEFAULT_DDG_LITE_URL_TEMPLATE),
    ):
        url = template.format(query=encoded_query)
        try:
            page = _open_html_search_page(url=url, timeout_ms=DEFAULT_NAVIGATION_TIMEOUT_MS)
            last_page = page
            results = _extract_search_results_from_html(page["html"], limit=limit)
            if not results:
                raise SearchRuntimeError(
                    "E_WEB_SEARCH_NO_RESULTS",
                    _build_search_no_results_message(
                        query=query,
                        final_url=page["final_url"],
                        title=page["title"],
                        html=page["html"],
                        provider_label=_duckduckgo_variant_label(variant),
                    ),
                    payload={"provider": "duckduckgo_html", "variant": variant},
                )
            attempts.append({"provider": "duckduckgo_html", "variant": variant, "status": "ok"})
            return {
                "provider_used": "duckduckgo_html",
                "variant": variant,
                "results": results,
                "attempts": attempts,
                "final_url": page["final_url"],
                "title": page["title"],
            }
        except SearchRuntimeError as exc:
            last_error = exc
            attempts.append(
                {
                    "provider": "duckduckgo_html",
                    "variant": variant,
                    "status": "failed",
                    "error_code": exc.error_code,
                    "detail": str(exc)[:240],
                }
            )
    error_code = str(last_error.error_code if last_error is not None else "E_WEB_RUNTIME_UNAVAILABLE").strip()
    raise SearchRuntimeError(
        error_code or "E_WEB_RUNTIME_UNAVAILABLE",
        _compose_search_attempts_failure(query=query, attempts=attempts, provider_label="DuckDuckGo HTTP search"),
        payload={
            "provider": "duckduckgo_html",
            "attempts": attempts,
            "final_url": str((last_page or {}).get("final_url") or "").strip(),
        },
    )


def playwright_search(
    *,
    query: str,
    limit: int,
    allow_query_resubmit: bool = True,
    include_metadata: bool = False,
) -> tuple[str, list[dict[str, Any]]] | dict[str, Any]:
    payload = _browser_assisted_search(
        query=query,
        limit=limit,
        allow_query_resubmit=allow_query_resubmit,
        timeout_ms=DEFAULT_NAVIGATION_TIMEOUT_MS,
    )
    if include_metadata:
        return payload
    return payload["provider_used"], payload["results"]


def playwright_browse(*, url: str, max_chars: int = DEFAULT_TEXT_LIMIT) -> dict[str, Any]:
    page = _open_page(url=url, timeout_ms=DEFAULT_NAVIGATION_TIMEOUT_MS)
    text = _extract_text_from_html(page["html"])
    if not text:
        raise PlaywrightRuntimeError(
            "E_WEB_NAVIGATION_FAILED",
            f"Playwright browse produced no readable page text for url={url!r}",
        )
    return {
        "provider_used": "playwright",
        "url": str(url).strip(),
        "final_url": str(page["final_url"]).strip(),
        "title": str(page["title"]).strip(),
        "text": text[:max(1, int(max_chars))],
    }


def _browser_assisted_search(
    *,
    query: str,
    limit: int,
    allow_query_resubmit: bool,
    timeout_ms: int,
) -> dict[str, Any]:
    sync_api = _import_playwright_sync_api()
    search_url = DEFAULT_BROWSER_SEARCH_URL_TEMPLATE.format(query=urllib.parse.quote_plus(str(query or "").strip()))
    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=False)
            page = context.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=int(timeout_ms))
            _wait_for_network_to_settle(page=page, timeout_ms=timeout_ms)
            payload = _capture_page_state(page)
            resubmitted = False
            if _looks_like_duckduckgo_search_portal(
                final_url=payload["final_url"],
                title=payload["title"],
                html=payload["html"],
            ):
                if allow_query_resubmit and _playwright_search_box_present(page):
                    _playwright_submit_query(page=page, query=query, timeout_ms=timeout_ms)
                    payload = _capture_page_state(page)
                    resubmitted = True
                if _looks_like_duckduckgo_search_portal(
                    final_url=payload["final_url"],
                    title=payload["title"],
                    html=payload["html"],
                ):
                    raise SearchRuntimeError(
                        "E_WEB_SEARCH_NO_RESULTS",
                        _build_search_no_results_message(
                            query=query,
                            final_url=payload["final_url"],
                            title=payload["title"],
                            html=payload["html"],
                            provider_label="Browser-assisted search",
                        ),
                        payload={
                            "provider": "playwright_search",
                            "attempts": [
                                {
                                    "provider": "playwright_search",
                                    "status": "failed",
                                    "error_code": "E_WEB_SEARCH_NO_RESULTS",
                                    "detail": _build_search_no_results_message(
                                        query=query,
                                        final_url=payload["final_url"],
                                        title=payload["title"],
                                        html=payload["html"],
                                        provider_label="Browser-assisted search",
                                    )[:240],
                                }
                            ],
                            "resubmitted": resubmitted,
                        },
                    )
            results = _extract_search_results_from_html(payload["html"], limit=limit)
            if not results:
                raise SearchRuntimeError(
                    "E_WEB_SEARCH_NO_RESULTS",
                    _build_search_no_results_message(
                        query=query,
                        final_url=payload["final_url"],
                        title=payload["title"],
                        html=payload["html"],
                        provider_label="Browser-assisted search",
                    ),
                        payload={
                            "provider": "playwright_search",
                            "attempts": [
                                {
                                    "provider": "playwright_search",
                                    "status": "failed",
                                    "error_code": "E_WEB_SEARCH_NO_RESULTS",
                                    "detail": _build_search_no_results_message(
                                        query=query,
                                        final_url=payload["final_url"],
                                        title=payload["title"],
                                        html=payload["html"],
                                        provider_label="Browser-assisted search",
                                    )[:240],
                                }
                            ],
                            "resubmitted": resubmitted,
                        },
                    )
            context.close()
            browser.close()
            return {
                "provider_used": "playwright_search",
                "results": results,
                "attempts": [{"provider": "playwright_search", "status": "ok"}],
                "resubmitted": resubmitted,
                "final_url": payload["final_url"],
                "title": payload["title"],
            }
    except SearchRuntimeError:
        raise
    except PlaywrightRuntimeError as exc:
        raise SearchRuntimeError(
            exc.error_code,
            str(exc),
            payload={
                "provider": "playwright_search",
                "attempts": [
                    {
                        "provider": "playwright_search",
                        "status": "failed",
                        "error_code": exc.error_code,
                        "detail": str(exc)[:240],
                    }
                ],
            },
        ) from exc
    except Exception as exc:
        raise SearchRuntimeError(
            "E_WEB_NAVIGATION_FAILED",
            f"Browser-assisted search failed for query={query!r}: {str(exc)[:240]}",
            payload={
                "provider": "playwright_search",
                "attempts": [
                    {
                        "provider": "playwright_search",
                        "status": "failed",
                        "error_code": "E_WEB_NAVIGATION_FAILED",
                        "detail": str(exc)[:240],
                    }
                ],
            },
        ) from exc


def _import_playwright_sync_api() -> Any:
    try:
        return importlib.import_module("playwright.sync_api")
    except Exception as exc:
        raise PlaywrightRuntimeError("E_WEB_RUNTIME_UNAVAILABLE", PLAYWRIGHT_INSTALL_HINT) from exc


def _wait_for_network_to_settle(*, page: Any, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=min(2000, int(timeout_ms)))
    except Exception:
        pass


def _capture_page_state(page: Any) -> dict[str, str]:
    html_text = str(page.content() or "")
    if not html_text:
        raise PlaywrightRuntimeError(
            "E_WEB_NAVIGATION_FAILED",
            f"Playwright navigation returned empty HTML for url={str(page.url or '').strip()!r}",
        )
    return {
        "final_url": str(page.url or "").strip(),
        "title": str(page.title() or "").strip(),
        "html": html_text,
    }


def _playwright_search_box_present(page: Any) -> bool:
    try:
        return page.query_selector('input[name="q"]') is not None
    except Exception:
        return False


def _playwright_submit_query(*, page: Any, query: str, timeout_ms: int) -> None:
    control = page.query_selector('input[name="q"]')
    if control is None:
        raise PlaywrightRuntimeError(
            "E_WEB_NAVIGATION_FAILED",
            "Browser-assisted search could not find a search box to resubmit the query.",
        )
    try:
        control.fill(str(query or "").strip())
        control.press("Enter")
    except Exception as exc:
        raise PlaywrightRuntimeError(
            "E_WEB_NAVIGATION_FAILED",
            f"Browser-assisted search failed while resubmitting the query: {str(exc)[:240]}",
        ) from exc
    _wait_for_network_to_settle(page=page, timeout_ms=timeout_ms)


def _open_page(*, url: str, timeout_ms: int) -> dict[str, str]:
    sync_api = _import_playwright_sync_api()

    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=False)
            page = context.new_page()
            page.goto(str(url).strip(), wait_until="domcontentloaded", timeout=int(timeout_ms))
            _wait_for_network_to_settle(page=page, timeout_ms=timeout_ms)
            payload = _capture_page_state(page)
            context.close()
            browser.close()
    except PlaywrightRuntimeError:
        raise
    except Exception as exc:
        raise PlaywrightRuntimeError(
            "E_WEB_NAVIGATION_FAILED",
            f"Playwright navigation failed for url={url!r}: {str(exc)[:240]}",
        ) from exc
    if not payload["html"]:
        raise PlaywrightRuntimeError(
            "E_WEB_NAVIGATION_FAILED",
            f"Playwright navigation returned empty HTML for url={url!r}",
        )
    return payload


def _open_html_search_page(*, url: str, timeout_ms: int) -> dict[str, str]:
    req = urllib.request.Request(
        str(url).strip(),
        method="GET",
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "agentos-next-web-search/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, int(timeout_ms) // 1000)) as resp:
            raw = resp.read()
            final_url = ""
            geturl = getattr(resp, "geturl", None)
            if callable(geturl):
                try:
                    final_url = str(geturl() or "").strip()
                except Exception:
                    final_url = ""
    except Exception as exc:
        raise SearchRuntimeError(
            "E_WEB_RUNTIME_UNAVAILABLE",
            f"DuckDuckGo HTTP search failed for url={url!r}: {str(exc)[:240]}",
        ) from exc
    html_text = raw.decode("utf-8", errors="replace")
    if not html_text:
        raise SearchRuntimeError(
            "E_WEB_SEARCH_NO_RESULTS",
            f"DuckDuckGo HTTP search returned empty HTML for url={url!r}",
        )
    return {
        "final_url": final_url or str(url).strip(),
        "title": _extract_title_from_html(html_text),
        "html": html_text,
    }


def _extract_search_results_from_html(content: str, *, limit: int) -> list[dict[str, Any]]:
    normalized = str(content or "")
    patterns = [
        re.compile(
            r'result__a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?result__snippet[^>]*>(?P<snippet>.*?)</(?:a|div)>',
            re.DOTALL | re.IGNORECASE,
        ),
        re.compile(
            r'data-testid="result-title-a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?data-testid="result-snippet"[^>]*>(?P<snippet>.*?)</',
            re.DOTALL | re.IGNORECASE,
        ),
        re.compile(
            r'<article[^>]*class="[^"]*result[^"]*"[^>]*>.*?<a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?<p[^>]*>(?P<snippet>.*?)</p>',
            re.DOTALL | re.IGNORECASE,
        ),
    ]
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for pattern in patterns:
        for match in pattern.finditer(normalized):
            item = _normalize_result(
                title=match.groupdict().get("title"),
                snippet=match.groupdict().get("snippet"),
                url=match.groupdict().get("url"),
            )
            key = (item["url"], item["title"])
            if not _is_usable_search_result(item) or key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= int(limit):
                return results
    if results:
        return results

    fallback = re.finditer(
        r'<a[^>]*href="(?P<url>[^"#][^"]*)"[^\>]*>(?P<title>.*?)</a>',
        normalized,
        re.DOTALL | re.IGNORECASE,
    )
    for match in fallback:
        item = _normalize_result(title=match.group("title"), snippet="", url=match.group("url"))
        key = (item["url"], item["title"])
        if not _is_usable_search_result(item) or key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= int(limit):
            break
    return results


def _build_search_no_results_message(
    *,
    query: str,
    final_url: str,
    title: str,
    html: str,
    provider_label: str = "DuckDuckGo HTTP search",
) -> str:
    if _looks_like_duckduckgo_search_portal(final_url=final_url, title=title, html=html):
        return (
            f"{provider_label} only returned the DuckDuckGo homepage/search portal without usable results "
            f"for query={query!r}"
        )
    normalized_final_url = str(final_url or "").strip()
    if normalized_final_url:
        return (
            f"{provider_label} returned no usable results for query={query!r}; "
            f"final_url={normalized_final_url!r}"
        )
    return f"{provider_label} returned no usable results for query={query!r}"


def _extract_title_from_html(content: str) -> str:
    match = re.search(r"<title[^>]*>(?P<title>.*?)</title>", str(content or ""), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return " ".join(_strip_tags(match.group("title")).split()).strip()


def _looks_like_duckduckgo_search_portal(*, final_url: str, title: str, html: str) -> bool:
    normalized_url = str(final_url or "").strip().lower()
    if "duckduckgo.com" not in normalized_url:
        return False
    normalized_html = str(html or "").lower()
    normalized_title = str(title or "").strip().lower()
    has_search_box = ('name="q"' in normalized_html) or ("search-form" in normalized_html)
    has_result_markers = (
        ("result__a" in normalized_html)
        or ('data-testid="result-title-a"' in normalized_html)
        or ('class="result' in normalized_html)
        or ("result-link" in normalized_html)
    )
    title_looks_like_homepage = normalized_title in {"duckduckgo", "duckduckgo - privacy, simplified.", ""}
    return has_search_box and not has_result_markers and title_looks_like_homepage


def _is_usable_search_result(item: dict[str, str]) -> bool:
    url = str(item.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return False
    normalized_url = url.lower()
    if "duckduckgo.com" in normalized_url:
        return False
    title = str(item.get("title") or "").strip().lower()
    if not title or title in {"duckduckgo", "privacy, simplified."}:
        return False
    return True


def _normalize_result(*, title: Any, snippet: Any, url: Any) -> dict[str, str]:
    return {
        "title": _clean_html_fragment(title),
        "snippet": _clean_html_fragment(snippet),
        "url": _normalize_result_url(url),
    }


def _extract_text_from_html(content: str) -> str:
    text = re.sub(r"<script.*?>.*?</script>", " ", str(content or ""), flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<noscript.*?>.*?</noscript>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return " ".join(text.split()).strip()


def _clean_html_fragment(value: Any) -> str:
    return _extract_text_from_html(str(value or ""))


def _strip_tags(value: Any) -> str:
    return re.sub(r"<[^>]+>", " ", str(value or ""))


def _normalize_result_url(value: Any) -> str:
    raw = html.unescape(str(value or "").strip())
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = "https://duckduckgo.com" + raw
    parsed = urllib.parse.urlparse(raw)
    host = str(parsed.netloc or "").strip().lower()
    path = str(parsed.path or "").strip()
    if "duckduckgo.com" in host and path.rstrip("/") == "/l":
        redirect = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        decoded = urllib.parse.unquote(str(redirect or "").strip())
        if decoded:
            return decoded
    return raw


def _duckduckgo_variant_label(variant: str) -> str:
    if str(variant or "").strip().lower() == "lite":
        return "DuckDuckGo Lite search"
    return "DuckDuckGo HTML search"


def _compose_search_attempts_failure(*, query: str, attempts: list[dict[str, Any]], provider_label: str) -> str:
    if not attempts:
        return f"{provider_label} failed for query={query!r}: no attempts were made"
    parts: list[str] = []
    for item in attempts:
        provider = str(item.get("provider") or "unknown").strip()
        variant = str(item.get("variant") or "").strip()
        status = str(item.get("status") or "failed").strip()
        error_code = str(item.get("error_code") or "").strip()
        detail = str(item.get("detail") or "").strip()
        label = provider if not variant else f"{provider}[{variant}]"
        if error_code and detail:
            parts.append(f"{label}:{status}:{error_code}:{detail}")
        elif error_code:
            parts.append(f"{label}:{status}:{error_code}")
        elif detail:
            parts.append(f"{label}:{status}:{detail}")
        else:
            parts.append(f"{label}:{status}")
    return f"{provider_label} failed for query={query!r}; attempts=" + " | ".join(parts)
