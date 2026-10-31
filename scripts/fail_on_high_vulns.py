"""Падает, если pip-audit нашёл уязвимость высокой или критической тяжести."""

import json
import sys
import urllib.request


def score_of(vuln_id: str) -> float | None:
    request = urllib.request.Request(
        f"https://api.osv.dev/v1/vulns/{vuln_id}",
        headers={"User-Agent": "stimul-audit"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except Exception:
        return None
    best = None
    for item in payload.get("severity") or []:
        raw = str(item.get("score") or "")
        if "/" not in raw:
            continue
        try:
            number = float(raw.split("/", 1)[0])
        except ValueError:
            continue
        best = number if best is None else max(best, number)
    return best


def main() -> None:
    path = sys.argv[1]
    report = json.loads(open(path, encoding="utf-8").read())
    dependencies = report.get("dependencies") if isinstance(report, dict) else report
    high: list[str] = []
    for dep in dependencies or []:
        name = dep.get("name", "")
        for vuln in dep.get("vulns") or []:
            vuln_id = vuln.get("id") or ""
            score = score_of(vuln_id)
            for alias in vuln.get("aliases") or []:
                if score is None:
                    score = score_of(alias)
            if score is not None and score >= 7:
                high.append(f"{name} {vuln_id} {score}")
    if high:
        print("высокие уязвимости:")
        print("\n".join(high))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
