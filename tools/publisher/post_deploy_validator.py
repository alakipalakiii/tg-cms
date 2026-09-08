from __future__ import annotations

import re
import urllib.request


def validate_public(base: str, paths: list[str]) -> dict:
    failures = []
    for path in paths:
        request = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": "MAHOON-M9-PUBLISHER-POSTDEPLOY/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", "ignore")
                if response.status != 200 or (path.startswith("/post/") and not re.search(r"<link[^>]+canonical", body, re.I)):
                    failures.append(path)
        except Exception:
            failures.append(path)
    return {"checked": len(paths), "failures": failures, "PASS": not failures}
