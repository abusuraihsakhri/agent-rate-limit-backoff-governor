# Agent Rate Limit Backoff Governor

> **Domain:** Autonomous Agent Systems & Context State Architecture  
> **Reference Guidelines & Standards:** `Distributed Systems RFC & State Machine Verification`

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg?logo=fastapi&logoColor=white)
![Audit Trail](https://img.shields.io/badge/Audit-HMAC--SHA256_Tamper--Evident-brightgreen.svg)
![Zero-PHI Guard](https://img.shields.io/badge/Guard-Zero--PHI_Outbound-blue.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)

</div>

---

## 📖 What It Does

**Agent Rate Limit Backoff Governor** is an advanced analytical and computational platform implementing Token-bucket algorithm & decorrelated jitter backoff rate limit governor.

---

## ⚙️ Key Capabilities & Algorithmic Modules

### 🔬 Core Algorithmic & Evaluation Engines

- **`JitterStrategy`** — dedicated module for jitter strategy evaluation and state verification.
- **`CircuitState`** — dedicated module for circuit state evaluation and state verification.
- **`BackoffStrategy`** — dedicated module for backoff strategy evaluation and state verification.
- **`RateLimitHeaders`** — dedicated module for rate limit headers evaluation and state verification.
- **`BackoffState`** — dedicated module for backoff state evaluation and state verification.
- **`CircuitBreakerState`** — dedicated module for circuit breaker state evaluation and state verification.

---

## 📐 Mathematical Formulation & Logic

```text
  """Calculate the backoff delay for the given attempt number."""
  current_state.delay = self.backoff.calculate_delay(current_state.attempt)
```

---

## 💻 CLI Quickstart & Usage

### 1. Guided Interactive Mode
```bash
python cli.py
```

### 2. Direct Parameterized Evaluation
```bash
python cli.py --endpoint <value> --capacity <value> --refill-rate <value> --max-requests <value>
```

### Parameter Reference
- `--endpoint`: Specifies input measurement or parameter value.
- `--capacity`: Specifies input measurement or parameter value.
- `--refill-rate`: Specifies input measurement or parameter value.
- `--max-requests`: Specifies input measurement or parameter value.
- `--base-delay`: Specifies input measurement or parameter value.
- `--max-delay`: Specifies input measurement or parameter value.
- `--threshold`: Specifies input measurement or parameter value.
- `--timeout`: Specifies input measurement or parameter value.
- `--jitter`: Specifies input measurement or parameter value.
- `--attempts`: Specifies input measurement or parameter value.

### Input Data Schema

| Field | Description | Requirement |
|:------|:------------|:------------|
| `task_id` | Parameter / observation metric | Required |
| `target_identifier` | Parameter / observation metric | Required |
| `primary_metric` | Parameter / observation metric | Required |
| `secondary_metric` | Parameter / observation metric | Required |
| `is_critical_flag` | Parameter / observation metric | Required |
| `status_descriptor` | Parameter / observation metric | Required |

---

## 🛡️ Security & Enterprise Architecture

* **Zero-PHI Outbound Interceptor:** Active AST and regex inspection blocking SSNs, MRNs, phone numbers, and patient identifiers.
* **Tamper-Evident HMAC-SHA256 Audit Trail:** Chained, cryptographically signed logs for every evaluation and state transition.
* **Air-Gapped LLM Reasoning Adapter:** Agnostic integration for local Ollama instances (`llama3`, `mistral`), Claude 3.5 Sonnet, GPT-4o, and deterministic test mocks.
* **Active Learning Bayesian Calibration:** Dynamic tracker updating worker reliability weights and monitoring Brier calibration drift.
* **FastAPI & Prometheus Telemetry:** Exposes OpenAPI 3.1 REST endpoints and operational Prometheus metrics (`/metrics`).

---

## 🧪 Testing & Verification

Run the automated test suite:

```bash
pytest -v
```

Execute high-throughput batch simulation benchmarks:

```bash
python simulator.py --tasks 1000 --concurrency 8
```

---

## 🐳 Container Deployment

```bash
docker build -t agent-rate-limit-backoff-governor .
docker run -p 8000:8000 agent-rate-limit-backoff-governor
```
