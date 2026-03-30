#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


HTTP_CLIENT_PATCH = """class HttpClient:
    def __init__(self, base_url: str, headers: dict[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = headers

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)

        body = None
        headers = dict(self.headers)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        for attempt in range(HTTP_MAX_RETRIES):
            request = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                    content = response.read()
                    if not content:
                        return {}
                    return json.loads(content.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", "ignore")
                if exc.code in {408, 409, 429, 500, 502, 503, 504} and attempt < HTTP_MAX_RETRIES - 1:
                    wait_seconds = min(30.0, 1.5 * (attempt + 1))
                    print(
                        f"Transient HTTP {exc.code} from {url}; retrying in {wait_seconds:.1f}s "
                        f"({attempt + 1}/{HTTP_MAX_RETRIES})...",
                        file=sys.stderr,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise RuntimeError(f"{method} {url} failed: {exc.code} {error_body}") from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt < HTTP_MAX_RETRIES - 1:
                    wait_seconds = min(30.0, 2.0 * (attempt + 1))
                    print(
                        f"Network timeout/error calling {url}: {exc}; retrying in {wait_seconds:.1f}s "
                        f"({attempt + 1}/{HTTP_MAX_RETRIES})...",
                        file=sys.stderr,
                    )
                    time.sleep(wait_seconds)
                    continue
                raise RuntimeError(f"{method} {url} failed after retries: {exc}") from exc
"""


def main() -> None:
    source_path = Path(__file__).with_name("sync_get_to_notion.py")
    source = source_path.read_text(encoding="utf-8", errors="replace")

    class_start = source.find("class HttpClient:")
    class_end = source.find("\n\nclass GetClient:")
    if class_start == -1 or class_end == -1 or class_end <= class_start:
        raise SystemExit("Error: failed to locate HttpClient section in sync_get_to_notion.py")

    patched = source[:class_start] + HTTP_CLIENT_PATCH + source[class_end:]
    namespace: dict[str, object] = {"__name__": "__main__", "__file__": str(source_path)}
    exec(compile(patched, str(source_path), "exec"), namespace)


if __name__ == "__main__":
    main()
