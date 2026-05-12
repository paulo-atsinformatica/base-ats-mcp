"""
Testes de integração contra stack Docker (FalkorDB + Indexer + MCP Server).
Executar APÓS: docker compose up -d
  python tests/test_integration.py
"""
import sys
import time
import json
import httpx

MCP_BASE = "http://localhost:8001"
ADMIN_TOKEN = "test-admin-token"


def section(title: str):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print('='*55)


def check(label: str, condition: bool, detail: str = ""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def wait_for_service(url: str, timeout: int = 60, interval: int = 3):
    print(f"  Aguardando {url}...", end="", flush=True)
    for _ in range(timeout // interval):
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code < 500:
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

    # ─── 1. Health Check ──────────────────────────────────────────
    section("1. Health Check")
    if not wait_for_service(f"{MCP_BASE}/health"):
        print("  [FAIL] MCP Server não está disponível. Verifique: docker compose ps")
        sys.exit(1)

    r = httpx.get(f"{MCP_BASE}/health", timeout=10)
    data = r.json()
    if not check("HTTP 200", r.status_code == 200):
        failures += 1
    if not check("database: true", data.get("database") is True, str(data)):
        failures += 1
    if not check("indexer status set", "indexer" in data, str(data)):
        failures += 1

    # ─── 2. MCP Manifest ──────────────────────────────────────────
    section("2. MCP Manifest (/mcp)")
    r = httpx.get(f"{MCP_BASE}/mcp", timeout=10)
    data = r.json()
    if not check("HTTP 200", r.status_code == 200):
        failures += 1
    tools = {t["name"] for t in data.get("tools", [])}
    for expected in ["search_knowledge", "get_document", "graph_neighbors"]:
        if not check(f"tool: {expected}", expected in tools):
            failures += 1

    # ─── 3. Auth bloqueada sem token ─────────────────────────────
    section("3. Segurança — /sync sem token")
    r = httpx.post(f"{MCP_BASE}/sync", timeout=10)
    if not check("HTTP 403", r.status_code == 403, f"got {r.status_code}"):
        failures += 1

    # ─── 4. Trigger Sync ─────────────────────────────────────────
    section("4. POST /sync (trigger indexação)")
    r = httpx.post(
        f"{MCP_BASE}/sync",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        timeout=120,
    )
    data = r.json()
    if not check("HTTP 200", r.status_code == 200, f"body: {data}"):
        failures += 1
    if not check("status: ok", data.get("status") == "ok", str(data)):
        failures += 1
    processed = data.get("processed", 0)
    check(f"arquivos processados: {processed}", processed >= 0)

    # ─── 5. Busca Semântica ───────────────────────────────────────
    section("5. POST /tools/search_knowledge")
    r = httpx.post(
        f"{MCP_BASE}/tools/search_knowledge",
        params={"query": "fechamento de caixa", "limit": 3},
        timeout=30,
    )
    if not check("HTTP 200", r.status_code == 200, f"got {r.status_code}"):
        failures += 1
    else:
        result = r.json().get("result", "")
        if not check("resultado não vazio", len(result) > 10, result[:100]):
            failures += 1

    # ─── 6. Get Document ─────────────────────────────────────────
    section("6. POST /tools/get_document")
    r = httpx.post(
        f"{MCP_BASE}/tools/get_document",
        params={"doc_id": "ROT-cadastro-fornecedores"},
        timeout=10,
    )
    if not check("HTTP 200", r.status_code == 200, f"got {r.status_code}"):
        failures += 1
    else:
        result = r.json().get("result", "")
        check("conteúdo retornado", len(result) > 20, result[:80])

    # ─── 7. Graph Neighbors ───────────────────────────────────────
    section("7. POST /tools/graph_neighbors")
    r = httpx.post(
        f"{MCP_BASE}/tools/graph_neighbors",
        params={"entity_name": "windows/faturamento", "depth": 1},
        timeout=10,
    )
    if not check("HTTP 200", r.status_code == 200, f"got {r.status_code}"):
        failures += 1
    else:
        result = r.json().get("result", "")
        check("resposta recebida", len(result) > 0)

    # ─── Resultado Final ──────────────────────────────────────────
    section("RESULTADO FINAL")
    total_checks = 15
    print(f"  Falhas: {failures}/{total_checks}")
    if failures == 0:
        print("  TODOS OS TESTES PASSARAM!")
    else:
        print(f"  {failures} teste(s) falharam.")
    return failures


if __name__ == "__main__":
    result = run_tests()
    sys.exit(result)
