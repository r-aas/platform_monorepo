---
name: platform-k3d-networking
description: |
  k3d networking patterns for the mewtwo cluster. Use when services can't reach each other,
  registry pulls fail, nip.io resolves wrong inside containers, DNS breaks after Colima restart,
  or pods can't reach host services (Ollama). Covers registry access, /etc/hosts patching,
  CoreDNS, and the nip.io trap.
version: 1.0.0
---

# Platform k3d Networking

## The nip.io Trap

nip.io encodes the IP in the hostname: `app.dev.127.0.0.1.nip.io` → resolves to `127.0.0.1`.

**On the Mac**: Works perfectly. 127.0.0.1 is your machine.
**Inside a container/pod**: 127.0.0.1 is the container itself. Every nip.io lookup returns
the WRONG address inside containers.

### Patterns That Break

| Scenario | Why It Breaks | Fix |
|----------|--------------|-----|
| Pod curling `app.dev.127.0.0.1.nip.io` | Resolves to pod-local 127.0.0.1 | Use k8s service DNS: `app.dev.svc.cluster.local` |
| CI job smoke-testing via ingress | Same — 127.0.0.1 is job container | Use `http://host.docker.internal` + `-H Host:app.dev.127.0.0.1.nip.io` |
| k3d node pulling from registry | `registry.mewtwo.127.0.0.1.nip.io` → 127.0.0.1 → node-local | Add `/etc/hosts` entry on each k3d node (see below) |
| ExternalName service to GitLab | ingress-nginx resolves via CoreDNS → 127.0.0.1 | Use ClusterIP + static Endpoints instead |

## Registry Access from k3d Nodes

k3d nodes need to pull images from GitLab's container registry (HTTP, no TLS).

### Correct Approach: /etc/hosts + registries.yaml

**Step 1**: Find the Docker gateway IP:
```bash
docker network inspect platform_monorepo_gitlab --format '{{(index .IPAM.Config 0).Gateway}}'
# Typically 172.23.0.1
```

**Step 2**: Add `/etc/hosts` entry on every k3d node:
```bash
GATEWAY_IP=172.23.0.1
for node in $(docker ps --filter name=k3d-mewtwo --format '{{.Names}}'); do
  docker exec $node sh -c "echo '$GATEWAY_IP registry.mewtwo.127.0.0.1.nip.io' >> /etc/hosts"
done
```

**Step 3**: Configure registries.yaml (skip TLS):
```yaml
# /etc/rancher/k3s/registries.yaml (on k3s data volume — survives restart)
mirrors: {}
configs:
  "registry.mewtwo.127.0.0.1.nip.io":
    tls:
      insecure_skip_verify: true
```

### DO NOT Use Registry Mirrors

The `mirrors:` block in registries.yaml proxies requests through k3s's built-in mirror.
This corrupts image digests, causing `unexpected commit digest` errors on pull.
Always leave `mirrors: {}` empty.

### /etc/hosts is Ephemeral

`/etc/hosts` entries on k3d nodes are lost on node restart (container recreation).
Must re-apply after `k3d cluster start` or node restart.

The `registries.yaml` file persists because it's on the k3s data volume.

## Host Service Access from Pods

Pods reach host-machine services (Ollama, Colima Docker) via `host.docker.internal`.

```yaml
env:
  - name: OPENAI_BASE_URL
    value: "http://host.docker.internal:11434/v1"
```

This works because k3d runs inside Colima's Docker, which provides `host.docker.internal`
DNS resolution to the Mac host.

## DNS After Colima Restart

After Colima restart, Tailscale DNS (192.168.5.2) may be unreachable from Docker containers.

**Fix**: Add public DNS fallback to Colima VM:
```bash
colima ssh
sudo sh -c 'cat > /etc/docker/daemon.json << EOF
{"dns": ["8.8.8.8", "8.8.4.4"]}
EOF'
sudo systemctl restart docker
```

Then restart k3d nodes: `docker restart $(docker ps --filter name=k3d-mewtwo -q)`

## k8s Internal DNS

Within the cluster, always use service DNS instead of nip.io:

| External (Mac browser) | Internal (pod-to-pod) |
|------------------------|----------------------|
| `http://gitlab.mewtwo.127.0.0.1.nip.io` | `http://gitlab-ce.platform.svc.cluster.local` |
| `http://app.dev.127.0.0.1.nip.io` | `http://app.dev.svc.cluster.local` |
| `http://argocd.platform.127.0.0.1.nip.io` | `http://argocd-server.platform.svc.cluster.local` |

## Colima Disk Pressure Cascade

When Colima VM disk fills:
1. k3d nodes get `node.kubernetes.io/disk-pressure` taint
2. Pods get evicted
3. After freeing space + Colima restart, taint may persist

**Fix**: Remove taint manually:
```bash
kubectl taint nodes $(kubectl get nodes -o name) node.kubernetes.io/disk-pressure- 2>/dev/null
```

Kubelet bitmap recovery can take 5+ minutes after disk-pressure clears.

## NodePort Allocator Corruption

After etcd/sqlite stress from disk-full: "failed to allocate nodePort: range is full"
despite few NodePorts in use.

**Fix**: `docker restart k3d-mewtwo-server-0` to rebuild allocation bitmap.

## Rationalizations to Reject

- "nip.io works on my Mac so it'll work in the pod" — NO, 127.0.0.1 is container-local
- "I'll use ExternalName service for GitLab" — NO, CoreDNS resolves it to 127.0.0.1
- "Registry mirrors will handle HTTP" — NO, mirrors corrupt digests
- "DNS will fix itself after restart" — NO, /etc/hosts must be re-applied manually
