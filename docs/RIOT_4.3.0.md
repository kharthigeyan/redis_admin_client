# RIOT 4.3.0 — Useful Commands

## Version

```
------------------------------------------------------------
riot 4.3.0
------------------------------------------------------------
Build time:   2025-04-01 00:17:45Z
Revision:     e958616d3942f2ff6c001e379ddebadc4d9bf8b2
JVM:          21.0.5 (Azul Systems, Inc. 21.0.5+11-LTS)
------------------------------------------------------------
```

---

## Introduction

RIOT 4.3 is used to help with migration of data from Redis to Valkey. Redis-to-Redis data copy can be performed using the RIOT open source tool.

**References**
- Docs: https://redis.io/docs/latest/integrate/riot/
- Docs: https://redis.github.io/riot/
- GitHub: https://github.com/redis/riot

---

## Access the RIOT Pod in Kubernetes

Execute the following commands to access the RIOT pod in a terminal.

```bash
# Authenticate to Kubernetes
# Session expires every 45 mins — re-run auth to stay connected
kubectl auth ...
kubectx <your-cluster-context>
kubens <your-namespace>

kubectl get pods | grep riot

kubectl exec -it <riot-pod-name> -- /bin/bash
```

---

## One-Time Replication

### Cluster → Cluster (Safe / Recommended)

> ✅ The configuration below is safer and less likely to cause redis-server restarts.
> Use conservative batch/thread settings to reduce load on the source.

```bash
riot replicate --struct \
  --batch 500 --scan-count 200 --threads 1 --read-threads 1 --read-batch 50 --read-queue 200 \
  --compare NONE \
  --source-cluster \
  --target-cluster \
  redis://<source-host> \
  redis://<target-host>
```

```bash
riot replicate --struct \
  --batch 1000 --scan-count 500 --threads 1 --read-threads 1 --read-batch 100 --read-queue 500 \
  --source-cluster \
  --target-cluster \
  redis://<source-host> \
  redis://<target-host>
```

---

### Cluster → Cluster (High Throughput)

> ⚠️ High thread/batch settings can cause redis-server restarts under load.
> Test in a staging environment before using in production.

```bash
riot replicate --struct \
  --batch 10000 --scan-count 10000 --threads 4 --read-threads 4 --read-batch 500 --read-queue 2000 \
  --source-cluster \
  --target-cluster \
  redis://<source-host> \
  redis://<target-host>
```

### Standalone → Cluster

```bash
riot replicate --struct \
  --batch 10000 --scan-count 10000 --threads 4 --read-threads 4 --read-batch 500 --read-queue 2000 \
  --target-cluster \
  redis://<source-host> \
  redis://<target-host>
```

### Cluster → Standalone

```bash
riot replicate --struct \
  --batch 10000 --scan-count 10000 --threads 4 --read-threads 4 --read-batch 500 --read-queue 2000 \
  --source-cluster \
  redis://<source-host> \
  redis://<target-host>
```

### Standalone → Standalone

```bash
riot replicate --struct \
  --batch 10000 --scan-count 10000 --threads 4 --read-threads 4 --read-batch 500 --read-queue 2000 \
  redis://<source-host> \
  redis://<target-host>
```

---

## Live Replication

### Prerequisites — Enable Keyspace Notifications

> **Important**: Keyspace notifications **must** be enabled on the source Redis instance before running RIOT in live mode. Without this, RIOT cannot detect real-time key updates, deletes, or other operations.

#### GCP Memorystore Redis Clusters

```bash
gcloud redis clusters update <cluster-name> \
  --region=<region> \
  --update-redis-config notify-keyspace-events=KEA
```

**Example:**

```bash
gcloud redis clusters update my-cluster \
  --region=us-central1 \
  --update-redis-config notify-keyspace-events=KEA
```

#### Standard Redis / Valkey Instances

```bash
redis-cli CONFIG SET notify-keyspace-events KEA
```

#### Verify Configuration

```bash
# GCP Memorystore Cluster
gcloud redis clusters describe <cluster-name> \
  --region=<region> \
  --format="yaml(redisConfigs)"

# Standard Redis / Valkey
redis-cli CONFIG GET notify-keyspace-events
```

#### What `KEA` Means

| Flag | Meaning |
|------|---------|
| `K` | Keyspace events (operations on keys) |
| `E` | Keyevent events (events that affect keys) |
| `A` | All events (generic commands: DEL, EXPIRE, etc.) |

---

### Live Replication Commands

#### Replicate db:0 (default)

```bash
riot replicate --mode=LIVE --struct \
  redis://<source-host> \
  redis://<target-host>
```

#### Replicate a specific database (e.g. db:8)

```bash
riot replicate --mode=LIVE --struct \
  redis://<source-host>/8 \
  redis://<target-host>/8
```

#### Cluster → Cluster (Live)

```bash
riot replicate --mode=LIVE --struct \
  --batch 10000 --scan-count 10000 --threads 4 --read-threads 4 --read-batch 500 --read-queue 2000 \
  --source-cluster \
  --target-cluster \
  redis://<source-host> \
  redis://<target-host>
```

---

## Export / Import to File

### Export to JSON file

```bash
riot file-export \
  --uri redis://<source-host> \
  dump.json \
  --content-type=STRUCT \
  --batch 500000 \
  --scan-count 500000 \
  --threads 1 \
  --type=json
```

### Validate the exported JSON file

```bash
jq . dump.json > /dev/null
```

### Import from JSON file (to cluster)

```bash
riot file-import \
  --cluster \
  --uri redis://<target-host>:6379 \
  dump.json
```

---

## Known Limitations / Bugs

- **Binary data**: RIOT cannot copy binary data — it replicates strings only.
- **JSON parse error**: https://github.com/redis/riot/issues/174
- **Large lists are silently skipped**: RIOT ignores copying lists that are very large. These must be copied manually outside RIOT.

---

## Manual Workaround for Large Lists

### 1. Find keys missing from the target

```bash
# Dump all keys from source and target
redis-cli -h <source-host> -n 0 --scan > source-unsorted.txt
redis-cli -h <target-host> -n 0 --scan > target-unsorted.txt

# Sort both files
sort source-unsorted.txt > source-sorted.txt
sort target-unsorted.txt > target-sorted.txt

# Diff to find missing keys
diff source-sorted.txt target-sorted.txt
```

### 2. Inspect the missing key

```bash
redis-cli -h <source-host> TYPE <key>
redis-cli -h <source-host> MEMORY USAGE <key>
redis-cli -h <source-host> LLEN <key>
```

### 3. Python script to copy the large list

```python
#!/usr/bin/python3
import redis
from tqdm import tqdm

SOURCE_HOST = "<source-host>"
TARGET_HOST = "<target-host>"
KEY = "<your-large-list-key>"

source_r = redis.Redis(host=SOURCE_HOST, port=6379, decode_responses=True)
target_r = redis.Redis(host=TARGET_HOST, port=6379, decode_responses=True)

list_len = source_r.llen(KEY)
print(f"{KEY} has {list_len} items on source.")

if target_r.exists(KEY):
    print(f"Deleting existing key '{KEY}' on target...")
    target_r.delete(KEY)

print("Fetching list from source...")
elements = source_r.lrange(KEY, 0, -1)

print("Copying to target...")
for item in tqdm(elements, desc="Copying", unit="item"):
    target_r.rpush(KEY, item)

print("Done. Verifying...")
target_len = target_r.llen(KEY)
print(f"Target {KEY} length: {target_len} (expected {list_len})")
```
