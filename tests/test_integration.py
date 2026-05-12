"""
Integration smoke tests against the Docker stack.

Run after:
  docker compose up -d

Optional env vars:
  MCP_BASE=http://localhost:8000
  ADMIN_TOKEN=test-admin-token
"""

import os
import sys
import time

import httpx


MCP_BASE = os.getenv("MCP_BASE", "http://localhost:8000")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "test-admin-token")
AUTH_HEADERS = {"X-API-Key": ADMIN_TOKEN}


def section(title: str):
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print("=" * 55)


def check(label: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" - {detail}" if detail else ""))
    return condition


def wait_for_service(url: str, timeout: int = 60, interval: int = 3):
    print(f"  Waiting for {url}...", end="", flush=True)
    for _ in range(timeout // interval):
        try:
            response = httpx.get(url, timeout=5)
            if response.status_code < 500:
                print(" OK")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(interval)
    print(" TIMEOUT")
    return False


def run_tests():
    failures = 0

    section("1. Health Check")
    if not wait_for_service(f"{MCP_BASE}/health"):
        print("  [FAIL] MCP Server is not available. Check: docker compose ps")
        sys.exit(1)

    response = httpx.get(f"{MCP_BASE}/health", timeout=10)
    data = response.json()
    failures += not check("HTTP 200", response.status_code == 200)
    failures += not check("database: true", data.get("database") is True, str(data))

    section("2. Auth blocks protected endpoint")
    response = httpx.post(f"{MCP_BASE}/api/knowledge/search", json={"query": "teste"}, timeout=10)
    failures += not check("HTTP 403", response.status_code == 403, f"got {response.status_code}")

    section("3. MCP tools manifest")
    response = httpx.get(f"{MCP_BASE}/mcp", headers=AUTH_HEADERS, timeout=10)
    failures += not check("HTTP 200", response.status_code == 200, f"got {response.status_code}")
    if response.status_code == 200:
        tools = {tool["name"] for tool in response.json().get("tools", [])}
        for expected in ["search_knowledge", "get_document", "graph_neighbors"]:
            failures += not check(f"tool: {expected}", expected in tools)

    section("4. Trigger sync")
    response = httpx.post(f"{MCP_BASE}/api/admin/sync", headers=AUTH_HEADERS, timeout=300)
    failures += not check("HTTP 200", response.status_code == 200, response.text[:200])
    if response.status_code == 200:
        data = response.json()
        failures += not check("status: ok", data.get("status") == "ok", str(data))

    section("5. Semantic search")
    response = httpx.post(
        f"{MCP_BASE}/api/knowledge/search",
        headers=AUTH_HEADERS,
        json={"query": "fechamento de caixa", "limit": 3},
        timeout=60,
    )
    failures += not check("HTTP 200", response.status_code == 200, f"got {response.status_code}")
    if response.status_code == 200:
        result = response.json().get("result", "")
        failures += not check("non-empty result", len(result) > 10, result[:100])

    section("RESULT")
    print(f"  Failures: {failures}")
    return failures


if __name__ == "__main__":
    sys.exit(run_tests())
