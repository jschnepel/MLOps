# Deployment instructions and evolution

These commands are implementation instructions. Docker, Helm, kubectl and a container runtime were not available here; no container or cluster run is claimed. Primary sources: SOURCES.md S16–S20.

## 1. Local Python reference

Use README.md first. Bind only to localhost, use synthetic data and keep runtime credentials private. The zero-third-party-dependency CLI is the quickest validation. FastAPI/TestClient tests passed in the reported environment; a fresh dependency install still needs online resolution.

## 2. Docker Compose reference

After resolving dependencies and verifying the Dockerfile:

```bash
docker compose build
docker compose up -d
docker compose logs api
curl --fail http://127.0.0.1:8000/health/live
```

Read private demo credentials through your local container session rather than hardcoding them in YAML:

```bash
docker compose exec api cat /app/runtime/demo_credentials.json
```

Do not paste the credentials into screenshots or issue reports. The service is bound to 127.0.0.1 and uses an internal Compose network. The default model is deterministic. The default Compose profile deliberately has no external model route or cloud connection. A real-model profile requires a documented local service mapping and updated egress controls.

```bash
docker compose down
```

Removing the named volume deletes local demo data; back it up only through a consistent database procedure. Do not use `down -v` casually on information you intend to retain.

## 3. Single-instance reference Kubernetes

The supplied chart is for exactly one SQLite-based replica and Recreate updates. It is a reference deployment, not the final API/worker topology. Review the templates before installation.

```bash
kind create cluster --name ops-demo --config deploy/kind.yaml
docker build -t operations-copilot:reference .
kind load docker-image operations-copilot:reference --name ops-demo
helm lint deploy/helm
helm template ops deploy/helm > /tmp/ops-rendered.yaml
helm upgrade --install ops deploy/helm --namespace ops --create-namespace
kubectl -n ops rollout status deployment/ops
kubectl -n ops port-forward service/ops 8000:8000
```

Check generated resource names against `helm template`; the supplied template currently uses `{{ .Release.Name }}`. Verify credentials privately with the actual pod name. Keep port forwarding local. Chart image defaults must match the image you loaded; see values.yaml.

This cluster definition does not establish NetworkPolicy enforcement. For the isolation milestone, use `deploy/kind-policy.yaml`, install a compatible pinned enforcement-capable CNI, and test allowed and disallowed connections. Do not report isolation until the actual tests pass. [S18]

```bash
helm uninstall ops --namespace ops
kind delete cluster --name ops-demo
```

Local cluster deletion is destructive to its storage. No real data should be present in this demonstration.

## 4. Target distributed chart: implement after PostgreSQL and leases

Create separate API, worker and MCP Deployments. Keep PostgreSQL and model configuration explicit. API/worker can share a built image but run different entry points. Add a separate migration Job, restricted service accounts, resource budgets, appropriate probes, graceful termination, narrow network allows, secret references and persistent database storage. Do not run migrations independently in every web replica.

Do not scale the model endpoint with the same rule as the HTTP API. Cap worker concurrency by measured model/provider capacity. For graceful shutdown, stop acquiring jobs, finish bounded work where safe, and rely on lease/reconciliation after termination. A PodDisruptionBudget is not an all-failure availability guarantee.

Reference NetworkPolicy denies outbound traffic because its data is local. The target requires explicit DNS, PostgreSQL, MCP, model, telemetry and optional channel destinations. Test egress restrictions with actual pods and the selected CNI; do not weaken them silently to make a demonstration pass.

## 5. Real-model local execution

On a machine with Ollama and a deliberately selected installed model:

```bash
export MODEL_MODE=ollama
export OLLAMA_MODEL='your-exact-installed-model-identifier'
export OLLAMA_BASE_URL='http://127.0.0.1:11434'
python -m uvicorn operations_copilot.api:create_app --factory --host 127.0.0.1 --port 8000
```

This selects the real adapter in the reference API, not MCP or LangGraph orchestration. Confirm actual schema compatibility, output quality and memory/latency behavior. No model was downloaded or evaluated during authoring. There is no automatic hosted fallback.

## 6. Optional AWS deployment

Only after local release gates pass, define Terraform for the selected EKS/network/database/identity resources, approve the budget, and document teardown. Use short-lived deployment credentials, private service boundaries, external secret management and measured capacity. No AWS resources or GitHub repository changes were performed for this kit.
