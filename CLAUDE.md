# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

Uses miniconda with a dedicated `redis_admin` environment (Python 3.12). Ray only supports up to Python 3.12 — do not upgrade to 3.13/3.14 until Ray adds support. Install dependencies directly with pip (poetry's lock file has outdated ray version pins):

```bash
# Create and activate the conda environment
conda create -n redis_admin python=3.12 -y
conda activate redis_admin

# Install dependencies (bypasses outdated ray version pin)
pip install "redis>=5.0.0" "pandas>=2.0.0" "ray==2.54.0" "ipcalc>=1.99.0" \
  "requests>=2.28.1" "plotly-express>=0.4.1" "plotly>=5.9.0" \
  "altair>=5.0.0" "seaborn>=0.13.0" "duckdb>=1.0.0" "pytest>=7.1.2"

# Install the project in editable mode (skip strict dep resolution)
pip install -e . --no-deps
```

## Commands

```bash
# Run all tests
conda run -n redis_admin pytest

# Run a single test
conda run -n redis_admin pytest tests/test_redis_admin_client.py::test_version -v

# Build package
conda run -n redis_admin pip install build && python -m build
```

## Architecture

This is a Python library (`redis_admin_client`) that provides a high-level interface for Redis administration and monitoring.

### Core Class: `RedisDB`

The entire library is built around the `RedisDB` class in `redis_admin_client/redis_admin_client.py`. It auto-detects standalone vs. cluster mode on instantiation and exposes all operations as methods returning pandas DataFrames.

**Key design decisions:**
- **Cluster-aware**: All methods branch on `self.cluster_mode` to handle multi-node operations, aggregating results across nodes automatically.
- **Ray for parallelism**: Batch key operations (e.g., `scankeys`) use Ray remote functions (`exec_in_pipe`) to distribute pipeline work across nodes in parallel.
- **Pipeline buffering**: Constants `PIPE_BUFFER_SIZE=10_000` and `SCAN_BUFFER_SIZE=500_000` control batch sizes for bulk operations.
- **DataFrames as output**: All public methods return pandas DataFrames, queryable via `duckdb` (replaced deprecated `pandasql`).

### Public API

| Method | Description |
|--------|-------------|
| `keyspace()` | Per-database key statistics |
| `scankeys(pipemode=True)` | Full key scan with type, TTL, idle time, memory |
| `slowlog()` | Slow query log from all nodes |
| `info()` | Server info from all nodes |
| `client_list()` | Connected clients |
| `check_for_traffic(wait_seconds=20)` | Detect active traffic |
| `supported_commands()` | All Redis commands with metadata |

### Dependencies

- `redis ^4.3.4` — Redis client (supports cluster mode)
- `pandas ^1.4.3` — All results returned as DataFrames
- `ray ^1.13.0` — Parallel pipeline execution
- `plotly`, `altair`, `seaborn` — Visualization
- `ray ^2.54.0` — Parallel pipeline execution (max supported Python: 3.12)
- `duckdb ^1.0.0` — SQL queries on DataFrames (replaces deprecated `pandasql`)
