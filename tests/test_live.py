"""
Live integration tests against a Valkey instance at 127.0.0.1:6379.
Run with: conda run -n redis_admin pytest tests/test_live.py -v
"""
import pytest
import pandas as pd
import redis

HOST = "127.0.0.1"
PORT = 6379


@pytest.fixture(scope="module")
def db():
    from redis_admin_client import RedisDB
    return RedisDB(HOST, PORT)


@pytest.fixture(scope="module", autouse=True)
def require_server():
    """Skip all tests if the server is not reachable."""
    try:
        c = redis.Redis(HOST, PORT, socket_timeout=2)
        c.ping()
    except Exception:
        pytest.skip("Valkey/Redis not reachable at 127.0.0.1:6379")


# ---------------------------------------------------------------------------
# keyspace()
# ---------------------------------------------------------------------------

class TestKeyspace:
    def test_returns_dataframe(self, db):
        df = db.keyspace()
        assert isinstance(df, pd.DataFrame)

    def test_expected_columns(self, db):
        df = db.keyspace()
        assert set(['Hostname', 'Port', '#dbs', '#keys']).issubset(df.columns)

    def test_has_rows(self, db):
        df = db.keyspace()
        assert len(df) > 0

    def test_key_count_positive(self, db):
        df = db.keyspace()
        total_keys = int(df['#keys'].iloc[0])
        assert total_keys > 0, "Expected sample keys to be present"


# ---------------------------------------------------------------------------
# scankeys()
# ---------------------------------------------------------------------------

class TestScankeys:
    def test_returns_dataframe(self, db):
        df = db.scankeys()
        assert isinstance(df, pd.DataFrame)

    def test_expected_columns(self, db):
        df = db.scankeys()
        assert set(['Name', 'Type', 'TTLs', 'Idletime', 'MemoryUsage']).issubset(df.columns)

    def test_all_key_types_present(self, db):
        df = db.scankeys()
        types = set(df['Type'].unique())
        assert 'string' in types
        assert 'hash' in types
        assert 'list' in types
        assert 'set' in types
        assert 'zset' in types

    def test_ttl_keys_with_expiry(self, db):
        df = db.scankeys()
        # str:user:2 and str:config:timeout have TTLs set
        ttl_df = df[df['TTLs'] > 0]
        assert len(ttl_df) >= 2, "Expected at least 2 keys with TTL"

    def test_no_pipemode_returns_same_shape(self, db):
        df_pipe = db.scankeys(pipemode=True)
        df_nopipe = db.scankeys(pipemode=False)
        assert df_pipe.shape == df_nopipe.shape

    def test_memory_usage_positive(self, db):
        df = db.scankeys()
        assert (df['MemoryUsage'].dropna() > 0).all()


# ---------------------------------------------------------------------------
# client_list()
# ---------------------------------------------------------------------------

class TestClientList:
    def test_returns_dataframe(self, db):
        df = db.client_list()
        assert isinstance(df, pd.DataFrame)

    def test_has_rows(self, db):
        df = db.client_list()
        assert len(df) > 0

    def test_has_addr_column(self, db):
        df = db.client_list()
        assert 'addr' in df.columns


# ---------------------------------------------------------------------------
# slowlog()
# ---------------------------------------------------------------------------

class TestSlowlog:
    def test_returns_dataframe(self, db):
        df = db.slowlog()
        assert isinstance(df, pd.DataFrame)

    def test_duration_ms_column_exists_if_nonempty(self, db):
        df = db.slowlog()
        if len(df) > 0:
            assert 'duration_ms' in df.columns
            assert 'start_time' in df.columns


# ---------------------------------------------------------------------------
# info()
# ---------------------------------------------------------------------------

class TestInfo:
    def test_returns_dataframe(self, db):
        df = db.info()
        assert isinstance(df, pd.DataFrame)

    def test_has_data(self, db):
        df = db.info()
        assert df is not None
        assert len(df) > 0


# ---------------------------------------------------------------------------
# supported_commands()
# ---------------------------------------------------------------------------

class TestSupportedCommands:
    def test_returns_dataframe(self, db):
        df = db.supported_commands()
        assert isinstance(df, pd.DataFrame)

    def test_has_rows(self, db):
        df = db.supported_commands()
        assert len(df) > 0


# ---------------------------------------------------------------------------
# check_for_traffic()
# ---------------------------------------------------------------------------

class TestCheckForTraffic:
    def test_returns_string(self, db):
        result = db.check_for_traffic(wait_seconds=2)
        assert result in ('No traffic', 'Traffic seen')

    def test_detects_traffic(self, db):
        """Generate activity during the window and confirm traffic is detected."""
        import threading, time
        import redis as r

        def generate_traffic():
            time.sleep(0.5)
            c = r.Redis(HOST, PORT, decode_responses=True)
            for _ in range(20):
                c.set("traffic:probe", "1")
                c.get("traffic:probe")
            c.close()

        t = threading.Thread(target=generate_traffic)
        t.start()
        result = db.check_for_traffic(wait_seconds=2)
        t.join()
        assert result == 'Traffic seen'
