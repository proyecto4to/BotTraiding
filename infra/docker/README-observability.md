# Observability (Fase 14)

## Metrics — Prometheus + Grafana

Every Python service embeds `prometheus-fastapi-instrumentator` in its
`app/main.py` (the same 8-line block in all 14 services) and exposes
`GET /metrics` with the default HTTP metrics:

| Metric | What it gives you |
|---|---|
| `http_requests_total{handler,method,status}` | request count / error rate (status is grouped: `2xx`, `4xx`, `5xx`...) |
| `http_request_duration_seconds_bucket` | latency histogram (p50/p95/p99 via `histogram_quantile`) |
| `http_requests_inprogress` | in-flight requests gauge |
| `http_request_size_bytes` / `http_response_size_bytes` | payload sizes |

`prometheus.yml` scrapes all 14 services on the compose network
(`<service>:8000`) plus Prometheus itself, every 15s.

Grafana is fully provisioned from `grafana/provisioning/`:

- **datasources**: Prometheus (`http://prometheus:9090`, default) and Loki
  (`http://loki:3100`), with fixed uids `prometheus` / `loki`.
- **dashboards**: everything in `grafana/dashboards/` is loaded into the
  "TradingPlatform" folder. `tradingplatform-overview.json` has per-service
  request rate, 5xx error rate, p95 latency, and a service-up table from `up`.

Open Grafana at <http://localhost:3001> (admin/admin), Prometheus at
<http://localhost:9090>.

## Logs — promtail -> Loki

Services write structured JSON log lines to stdout (e.g. the gateway's audit
middleware). The compose stack ships them with **promtail** using Docker
service discovery: `promtail-config.yml` mounts `/var/run/docker.sock`,
discovers every container in the project and pushes its stdout/stderr to Loki
labelled with `service` (compose service name) and `container`.

Query examples in Grafana Explore (Loki datasource):

```logql
{service="gateway"} | json                       # parsed audit lines
{service="risk-engine"} |= "risk.rejected"       # rejections
sum by (service) (rate({project="docker"}[5m]))  # log volume per service
```

Alternative (not used here): Grafana's Loki **docker logging driver**
(`docker plugin install grafana/loki-docker-driver`) pushes logs without a
promtail container, but requires installing a host-level docker plugin on
every machine, so the self-contained promtail approach was chosen for the
dev stack.

Note: promtail needs access to the Docker socket. On Docker Desktop
(Windows/macOS) the `/var/run/docker.sock` mount works out of the box; on a
hardened host you may prefer to point `docker_sd_configs.host` at a socket
proxy.
