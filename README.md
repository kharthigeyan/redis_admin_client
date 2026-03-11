# redis_admin_client

A Python client for **Redis**, **Valkey**, and **DragonflyDB** administration and monitoring.

## Features

- Connect to standalone or cluster deployments
- Inspect keyspace — key counts, types, TTLs, idle times, memory usage
- Retrieve server info and slow query logs across all cluster nodes
- List connected clients
- Detect live traffic on an instance
- Parallel key scanning using Ray for large keyspaces

## Installation

```bash
conda create -n redis_admin python=3.12 -y
conda activate redis_admin

pip install "redis>=5.0.0" "pandas>=2.0.0" "ray==2.54.0" "ipcalc>=1.99.0" \
  "requests>=2.28.1" "plotly-express>=0.4.1" "plotly>=5.9.0" \
  "altair>=5.0.0" "seaborn>=0.13.0" "duckdb>=1.0.0"

pip install redis_admin_client
```

## Usage

```python
from redis_admin_client import RedisDB

db = RedisDB("localhost", 6379)

# Key distribution across the keyspace
db.keyspace()

# Scan all keys with type, TTL, idle time, and memory usage
db.scankeys()

# Slow query log
db.slowlog()

# Server info
db.info()

# Connected clients
db.client_list()

# Check if the instance is receiving traffic
db.check_for_traffic(wait_seconds=20)
```

## Compatibility

| Server       | Standalone | Cluster |
|--------------|:----------:|:-------:|
| Redis        | ✓          | ✓       |
| Valkey       | ✓          | ✓       |
| DragonflyDB  | ✓          | ✓       |

## Requirements

- Python 3.12+
- Ray 2.54 (parallel pipeline execution; max supported Python: 3.12)
