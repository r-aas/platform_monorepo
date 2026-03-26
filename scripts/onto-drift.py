#!/usr/bin/env python3
"""onto-drift.py — detect configuration drift between ontology and live cluster.

Compares what the ontology declares vs what kubectl reports. Catches:
- Missing services (declared but not running)
- Ghost services (running but not declared)
- Port mismatches
- Ingress host mismatches
- Broken dependencies (depends on a service that's not Ready)
- Health endpoint drift
"""
import json, subprocess, http.client, sys
from urllib.parse import urlparse

URL = "http://open-ontologies.genai.127.0.0.1.nip.io/mcp"
NAMESPACES = ["genai", "platform"]


# ── MCP client ────────────────────────────────────────────────

def mcp_session(url):
    parsed = urlparse(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    def post(body):
        conn.request("POST", parsed.path, json.dumps(body).encode(), headers)
        resp = conn.getresponse()
        sid = resp.getheader("mcp-session-id")
        if sid:
            headers["Mcp-Session-Id"] = sid
        raw = resp.read().decode()
        for line in raw.split("\n"):
            if line.startswith("data: {"):
                return json.loads(line[6:])
        return {}

    # Init
    post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "drift-check", "version": "1.0.0"}}})
    post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    return conn, headers, post


def sparql(post, query, id=10):
    resp = post({"jsonrpc": "2.0", "id": id, "method": "tools/call",
                  "params": {"name": "onto_query", "arguments": {"query": query}}})
    content = resp.get("result", {}).get("content", [])
    for c in content:
        try:
            return json.loads(c.get("text", "{}"))
        except:
            pass
    return {}


def clean_val(v):
    """Extract value from SPARQL result binding."""
    val = v.get("value", "") if isinstance(v, dict) else str(v)
    # Strip quotes and datatype suffixes
    if val.startswith('"'):
        val = val.split('"')[1]
    if "#" in val:
        val = val.split("#")[-1]
    return val


# ── Kubernetes queries ────────────────────────────────────────

def kubectl_json(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=10)
        return json.loads(out)
    except:
        return {}


def get_k8s_services():
    """Get all services from target namespaces."""
    services = {}
    for ns in NAMESPACES:
        data = kubectl_json(f"kubectl get svc -n {ns} -o json")
        for svc in data.get("items", []):
            name = svc["metadata"]["name"]
            ports = svc.get("spec", {}).get("ports", [])
            port = ports[0]["port"] if ports else None
            services[f"{ns}/{name}"] = {"port": port, "namespace": ns, "name": name}
    return services


def get_k8s_endpoints():
    """Get endpoint readiness keyed by service name (ns/svc)."""
    endpoints = {}
    for ns in NAMESPACES:
        data = kubectl_json(f"kubectl get endpoints -n {ns} -o json")
        for ep in data.get("items", []):
            name = ep["metadata"]["name"]
            # A service has ready endpoints if any subset has addresses
            subsets = ep.get("subsets", [])
            has_ready = any(s.get("addresses") for s in subsets)
            endpoints[f"{ns}/{name}"] = {"ready": has_ready}
    return endpoints


def get_k8s_ingresses():
    """Get ingress hosts from target namespaces. Returns {ns/svc: set(hosts)}."""
    ingresses = {}
    for ns in NAMESPACES:
        data = kubectl_json(f"kubectl get ingress -n {ns} -o json")
        for ing in data.get("items", []):
            rules = ing.get("spec", {}).get("rules", [])
            for rule in rules:
                host = rule.get("host", "")
                for path in rule.get("http", {}).get("paths", []):
                    svc_name = path.get("backend", {}).get("service", {}).get("name", "")
                    key = f"{ns}/{svc_name}"
                    ingresses.setdefault(key, set()).add(host)
    return ingresses


# ── Ontology queries ──────────────────────────────────────────

def get_onto_services(post):
    """Get declared services from ontology."""
    result = sparql(post, """
        PREFIX p: <http://r-aas.dev/ontology/platform#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?svc ?label ?port ?protocol ?addr ?ingress ?health WHERE {
            ?svc a/rdfs:subClassOf* p:Service .
            ?svc p:port ?port .
            ?svc rdfs:label ?label .
            OPTIONAL { ?svc p:protocol ?protocol }
            OPTIONAL { ?svc p:address ?addr }
            OPTIONAL { ?svc p:ingressHost ?ingress }
            OPTIONAL { ?svc p:healthPath ?health }
        }
    """, id=20)
    services = {}
    for row in result.get("results", []):
        iri = clean_val(row.get("svc", {}))
        services[iri] = {
            "label": clean_val(row.get("label", {})),
            "port": int(clean_val(row.get("port", {}))) if row.get("port") else None,
            "protocol": clean_val(row.get("protocol", {})) if row.get("protocol") else None,
            "address": clean_val(row.get("addr", {})) if row.get("addr") else None,
            "ingress": clean_val(row.get("ingress", {})) if row.get("ingress") else None,
            "health": clean_val(row.get("health", {})) if row.get("health") else None,
        }
    return services


def get_onto_dependencies(post):
    """Get declared dependencies from ontology."""
    result = sparql(post, """
        PREFIX p: <http://r-aas.dev/ontology/platform#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?from ?fromLabel ?to ?toLabel WHERE {
            ?from p:dependsOn ?to .
            ?from rdfs:label ?fromLabel .
            ?to rdfs:label ?toLabel .
        }
    """, id=30)
    deps = []
    for row in result.get("results", []):
        deps.append({
            "from": clean_val(row.get("from", {})),
            "from_label": clean_val(row.get("fromLabel", {})),
            "to": clean_val(row.get("to", {})),
            "to_label": clean_val(row.get("toLabel", {})),
        })
    return deps


def get_onto_ns_membership(post):
    """Get which namespace each service belongs to."""
    result = sparql(post, """
        PREFIX p: <http://r-aas.dev/ontology/platform#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?ns ?nsLabel ?svc WHERE {
            ?ns a p:Namespace .
            ?ns rdfs:label ?nsLabel .
            ?ns p:contains ?svc .
        }
    """, id=40)
    membership = {}
    for row in result.get("results", []):
        svc = clean_val(row.get("svc", {}))
        ns = clean_val(row.get("nsLabel", {}))
        membership[svc] = ns
    return membership


# ── Drift checks ──────────────────────────────────────────────

def check_drift():
    conn, headers, post = mcp_session(URL)

    # Load ontology into the server
    post({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
          "params": {"name": "onto_load", "arguments": {"path": "/ontology/platform.ttl"}}})
    post({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
          "params": {"name": "onto_load", "arguments": {"path": "/ontology/platform-instances.ttl"}}})
    post({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
          "params": {"name": "onto_reason", "arguments": {"profile": "rdfs"}}})

    # Gather data
    onto_svcs = get_onto_services(post)
    onto_deps = get_onto_dependencies(post)
    onto_ns = get_onto_ns_membership(post)
    k8s_svcs = get_k8s_services()
    k8s_eps = get_k8s_endpoints()
    k8s_ingresses = get_k8s_ingresses()

    conn.close()

    issues = []

    # Build lookup from ontology address → k8s key
    onto_to_k8s = {}
    for iri, svc in onto_svcs.items():
        addr = svc.get("address", "")
        if addr and ".svc.cluster.local" in addr:
            # e.g. genai-litellm.genai.svc.cluster.local → genai/genai-litellm
            parts = addr.split(".")
            svc_name = parts[0]
            ns = parts[1] if len(parts) > 1 else ""
            onto_to_k8s[iri] = f"{ns}/{svc_name}"
        elif addr:
            # Host service (e.g., ollama at 192.168.5.2) — skip k8s checks
            onto_to_k8s[iri] = None

    # 1. Missing services (in ontology, not in k8s)
    for iri, k8s_key in onto_to_k8s.items():
        if k8s_key is None:
            continue  # host service
        svc = onto_svcs[iri]
        if k8s_key not in k8s_svcs:
            issues.append(("MISSING", f"{svc['label']} — declared in ontology but no k8s Service at {k8s_key}"))

    # 2. Port mismatches
    for iri, k8s_key in onto_to_k8s.items():
        if k8s_key is None or k8s_key not in k8s_svcs:
            continue
        svc = onto_svcs[iri]
        k8s_port = k8s_svcs[k8s_key]["port"]
        if svc["port"] and k8s_port and svc["port"] != k8s_port:
            issues.append(("PORT", f"{svc['label']} — ontology says :{svc['port']}, k8s has :{k8s_port}"))

    # 3. Ingress host mismatches
    for iri, k8s_key in onto_to_k8s.items():
        if k8s_key is None:
            continue
        svc = onto_svcs[iri]
        if svc.get("ingress"):
            k8s_hosts = k8s_ingresses.get(k8s_key, set())
            if k8s_hosts and svc["ingress"] not in k8s_hosts:
                issues.append(("INGRESS", f"{svc['label']} — ontology: {svc['ingress']}, k8s: {', '.join(sorted(k8s_hosts))}"))
            elif not k8s_hosts:
                issues.append(("INGRESS", f"{svc['label']} — ontology declares ingress {svc['ingress']} but none found in k8s"))

    # 4. Broken dependencies (dependency target not Ready via endpoints)
    for dep in onto_deps:
        to_k8s = onto_to_k8s.get(dep["to"])
        if to_k8s is None:
            continue
        ep = k8s_eps.get(to_k8s)
        if ep and not ep["ready"]:
            issues.append(("DEP", f"{dep['from_label']} dependsOn {dep['to_label']} — {dep['to_label']} has no ready endpoints"))
        elif not ep:
            issues.append(("DEP", f"{dep['from_label']} dependsOn {dep['to_label']} — no endpoints found for {dep['to_label']}"))

    # 5. Ghost services (in k8s but not in ontology)
    # Skip: headless services, infra, and known sub-components
    GHOST_SKIP = [
        "kube-", "ingress-nginx", "local-path", "metrics",
        "-headless", "-hl",           # headless StatefulSet services
        "-console",                   # ancillary UIs (minio-console)
        "argocd-redis", "argocd-repo-server", "argocd-applicationset",  # ArgoCD internals
        "gitlab-runner",              # CI runner, not a platform service
    ]
    known_k8s_keys = set(v for v in onto_to_k8s.values() if v)
    for k8s_key, info in k8s_svcs.items():
        if any(skip in k8s_key for skip in GHOST_SKIP):
            continue
        if k8s_key not in known_k8s_keys:
            issues.append(("GHOST", f"{k8s_key} — running in k8s but not declared in ontology"))

    # Output
    if not issues:
        print("No drift detected — ontology matches cluster state.")
        return 0

    print(f"Found {len(issues)} issue(s):\n")
    severity_order = {"DEP": 0, "MISSING": 1, "PORT": 2, "INGRESS": 3, "GHOST": 4}
    issues.sort(key=lambda x: severity_order.get(x[0], 99))

    icons = {"DEP": "!!!", "MISSING": "XXX", "PORT": "=/=", "INGRESS": "~~~", "GHOST": "???"}
    for kind, msg in issues:
        print(f"  [{icons.get(kind, '   ')}] {kind:8s} {msg}")

    return len(issues)


if __name__ == "__main__":
    sys.exit(min(check_drift(), 255))
