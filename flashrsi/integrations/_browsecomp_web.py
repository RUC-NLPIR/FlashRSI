"""Search services and bounded direct or Jina public-page reading."""

import ipaddress
import json
import socket
from functools import partial
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

_MAX_BYTES = 2 * 1024 * 1024


def _http_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Requires an HTTP(S) URL without credentials")
    return parsed


def _public_url(url):
    parsed = _http_url(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    addresses = socket.getaddrinfo(
        parsed.hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global for item in addresses
    ):
        raise ValueError("Web reading requires a public address")
    return addresses


def _connect(addresses, _address, timeout, source_address):
    # Connect numeric sockaddr values from the validated lookup. Calling
    # create_connection(hostname) here would resolve again and allow rebinding.
    error = OSError("No reachable public address")
    for family, kind, protocol, _, address in addresses:
        connection = None
        try:
            connection = socket.socket(family, kind, protocol)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                connection.settimeout(timeout)
            if source_address:
                connection.bind(source_address)
            connection.connect(address)
            return connection
        except OSError as exc:
            error = exc
            if connection is not None:
                connection.close()
    raise error


def _connection(connection_type, request, host, **kwargs):
    addresses = _public_url(request.full_url)
    connection = connection_type(host, **kwargs)
    connection._create_connection = partial(_connect, addresses)
    return connection


class _HTTP(HTTPHandler):
    def http_open(self, req):
        return self.do_open(partial(_connection, HTTPConnection, req), req)


class _HTTPS(HTTPSHandler):
    def https_open(self, req):
        # Keep the original hostname for HTTP Host, TLS SNI and certificate
        # verification; only the socket connection uses the checked IP address.
        return self.do_open(
            partial(_connection, HTTPSConnection, req), req, context=self._context
        )


class _Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _body(response):
    data = response.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise ValueError("Web response exceeds 2 MiB")
    return data


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # Service credentials must never follow a redirect to another host.
        raise ValueError("Web service redirects are not supported")


def search(config, query, top_k):
    provider = config["provider"]
    body = {"query": query}
    if provider == "tavily":
        body.update(
            max_results=top_k,
            search_depth=config["search_depth"],
            include_answer=False,
            include_raw_content=False,
            include_images=False,
        )
    elif provider == "serper":
        body = {"q": query, "num": top_k}
    else:
        body["top_k"] = top_k
    headers = {"Content-Type": "application/json", **config.get("headers", {})}
    if config.get("api_key"):
        if provider == "serper":
            headers["X-API-KEY"] = config["api_key"]
        else:
            headers["Authorization"] = "Bearer " + config["api_key"]
    request = Request(config["url"], json.dumps(body).encode(), headers)

    with build_opener(_NoRedirect()).open(
        request, timeout=config["timeout"]
    ) as response:
        value = json.loads(_body(response))
    results = value["organic"] if provider == "serper" else value["results"]
    if not isinstance(results, list):
        raise ValueError("Search response requires results")
    public = []
    for item in results[:top_k]:
        if provider == "serper":
            item = {
                "title": item.get("title"),
                "url": item.get("link"),
                "content": item.get("snippet", ""),
            }
        if any(
            not isinstance(item.get(key), str) for key in ("title", "url", "content")
        ):
            raise ValueError("Search results require title, url and content strings")
        _http_url(item["url"])
        public.append(
            {
                "title": item["title"],
                "url": item["url"],
                "content": item["content"][:4000],
            }
        )
    return {"results": public}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = []
        self.row = None
        self.cell = None
        self.tables = []
        self.table_chars = 0

    def _text_target(self):
        if self.cell is not None:
            return self.cell
        parent_cell = self.tables[-1][1] if self.tables else None
        return parent_cell if parent_cell is not None else self.parts

    def _finish_cell(self):
        if self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None

    def _finish_row(self):
        if self.row is not None:
            self._finish_cell()
            # JSON rows preserve empty columns and escape delimiters in cell
            # text even after the reader normalizes surrounding whitespace.
            rendered = json.dumps(self.row, ensure_ascii=False)
            # Nested row strings acquire escapes again in their parent. Bound
            # total expansion as well as the downloaded HTML to avoid blow-up.
            self.table_chars += len(rendered)
            if self.table_chars > _MAX_BYTES:
                raise ValueError("Expanded table content exceeds character limit")
            self._text_target().append("\n" + rendered + "\n")
            self.row = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag == "table":
            # An inner table writes its rows into the enclosing cell. Restore
            # that cell afterwards so following outer columns keep their places.
            self._text_target().append("\n")
            self.tables.append((self.row, self.cell))
            self.row, self.cell = None, None
        if tag == "tr":
            self._finish_row()
            self.row = []
        if tag in ("td", "th"):
            if self.row is None:
                self.row = []
            self._finish_cell()
            self.cell = []
        if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3"):
            self._text_target().append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            if self.hidden[-1] == tag:
                self.hidden.pop()
            return
        if tag in ("td", "th"):
            self._finish_cell()
        if tag in ("tr", "table"):
            self._finish_row()
        if tag == "table" and self.tables:
            self.row, self.cell = self.tables.pop()
            self._text_target().append("\n")
        if tag in ("p", "div", "li", "tr"):
            self._text_target().append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self._text_target().append(data)

    def close(self):
        super().close()
        self._finish_row()
        while self.tables:
            self.row, self.cell = self.tables.pop()
            self._finish_row()


def read(config, url):
    _http_url(url)
    reader = config.get("reader", {})
    if reader.get("provider") == "jina":
        _public_url(url)
        request = Request(
            reader["url"],
            json.dumps({"url": url}).encode(),
            {
                "Content-Type": "application/json",
                "Accept": "text/plain",
                "Authorization": "Bearer " + reader["api_key"],
                "X-Respond-With": "markdown",
            },
        )
        with build_opener(_NoRedirect()).open(
            request, timeout=config["timeout"]
        ) as response:
            text = _body(response).decode("utf-8", errors="replace")
        limit = config["max_page_chars"]
        return {"url": url, "content": text[:limit], "truncated": len(text) > limit}
    request = Request(
        url,
        headers={
            "User-Agent": "FlashRSI-BrowseComp/0.1",
            "Accept": "text/html,text/plain",
        },
    )
    # Read directly: a forwarding proxy could resolve the hostname itself and
    # bypass socket address validation. Search service proxy behavior is separate.
    opener = build_opener(ProxyHandler({}), _HTTP(), _HTTPS(), _Redirect())
    with opener.open(request, timeout=config["timeout"]) as response:
        media = response.headers.get_content_type()
        if media not in ("text/html", "application/xhtml+xml", "text/plain"):
            raise ValueError("Web reading supports HTML or plain text")
        text = _body(response).decode(
            response.headers.get_content_charset() or "utf-8", errors="replace"
        )
        final_url = response.geturl()
    if media != "text/plain":
        parser = _Text()
        parser.feed(text)
        parser.close()
        text = "".join(parser.parts)
    text = "\n".join(
        " ".join(line.split()) for line in text.splitlines() if line.strip()
    )
    limit = config["max_page_chars"]
    return {"url": final_url, "content": text[:limit], "truncated": len(text) > limit}
