
# pip install ipcalc plotly duckdb ray pyarrow fastparquet

import io
import socket
import requests
import json
import ipcalc
from datetime import datetime

import ray
import plotly.express as px
import redis as r
import numpy as np
import time
import pandas as pd
import duckdb


ray.init(ignore_reinit_error=True)

PIPE_BUFFER_SIZE = 10_000
SCAN_BUFFER_SIZE = 500_000
SOCKET_TIMEOUT   =      10  # in seconds


def resolve_ip(ip):
    try:
        hostname = socket.gethostbyaddr(ip)[0]
        return hostname
    except socket.herror:
        return ip


@ray.remote
def exec_in_pipe(hostname, port, key_list, cmd, batch_size=PIPE_BUFFER_SIZE):
    conn = r.Redis(host=hostname, port=port, socket_timeout=SOCKET_TIMEOUT, decode_responses=True)
    pipe = conn.pipeline(transaction=False)
    full_result = []
    while len(key_list) > 0:
        batch = key_list[:batch_size]
        if cmd == 'idletime':
            for key in batch:
                pipe.object('idletime', key)
        else:
            pipe_cmd = getattr(pipe, cmd)
            for key in batch:
                pipe_cmd(key)
        full_result += pipe.execute()
        key_list = key_list[batch_size:]
    pipe.close()
    return full_result


pd.set_option('display.max_colwidth', 500)
pd.set_option('display.max_columns', 500)
pd.options.display.max_rows = 500


class RedisDB:
    def __init__(self, host, port=6379):
        self.host = host
        self.port = port
        self.conn = r.Redis(host, port, socket_timeout=SOCKET_TIMEOUT, decode_responses=True)
        self.redis_mode = self.conn.info()['redis_mode']
        if self.redis_mode == 'cluster':
            primary_nodes = []
            replica_nodes = []
            nodes_dict = self.conn.cluster('nodes')
            for ids in list(nodes_dict):
                if 'master' in nodes_dict[ids]['flags']:
                    primary_nodes.append(ids.split('@')[0].split(':'))
                if 'slave' in nodes_dict[ids]['flags']:
                    replica_nodes.append(ids.split('@')[0].split(':'))
            self.primary_nodes = primary_nodes
            self.replica_nodes = replica_nodes
            self.nodes = primary_nodes + replica_nodes

    def keyspace(self):
        if self.redis_mode == 'standalone':
            conn1 = r.Redis(self.host, self.port, socket_timeout=SOCKET_TIMEOUT)
            keyspace = [conn1.info()[db]['keys'] for db in conn1.info() if db.startswith('db')]
            return pd.DataFrame(
                [(self.host, self.port, str(len(keyspace)), str(np.array(keyspace).sum()))],
                columns=['Hostname', 'Port', '#dbs', '#keys']
            )
        elif self.redis_mode == 'cluster':
            output_list = []
            for h in self.primary_nodes:
                conn1 = r.Redis(h[0], h[1], socket_timeout=10)
                keyspace = [conn1.info()[db]['keys'] for db in conn1.info() if db.startswith('db')]
                output_list.append((h[0], h[1], str(len(keyspace)), str(np.array(keyspace).sum())))
                conn1.close()
            return pd.DataFrame(output_list, columns=['Hostname', 'Port', '#dbs', '#keys'])

    def supported_commands(self):
        conn1 = r.Redis(self.host, self.port, socket_timeout=SOCKET_TIMEOUT)
        data = conn1.command()
        return pd.json_normalize([data[x] for x in data])

    def client_list(self):
        if self.redis_mode == 'standalone':
            return pd.DataFrame(self.conn.client_list())
        elif self.redis_mode == 'cluster':
            master_df = pd.DataFrame()
            for h in self.primary_nodes:
                tmp_conn = r.Redis(h[0], h[1], socket_timeout=SOCKET_TIMEOUT)
                df = pd.DataFrame(tmp_conn.client_list())
                tmp_conn.close()
                df['node'] = f'{h[0]}:{h[1]}'
                master_df = pd.concat([master_df, df], axis=0)
            master_df.reset_index(drop=True, inplace=True)
            master_df.astype(str)
            return master_df

    def client_hosts(self):
        if self.redis_mode == 'standalone':
            for x in set(x.split(':')[0] for x in pd.DataFrame(self.conn.client_list())['addr']):
                ip_subnet = query_ip(x)
                print(x, ip_subnet)

    def scankeys(self, pipemode=True):
        if self.redis_mode == 'standalone':
            tmp_keyname = list(self.conn.scan_iter(count=SCAN_BUFFER_SIZE))
            if pipemode:
                tmp_type     = ray.get(exec_in_pipe.remote(self.host, self.port, tmp_keyname, 'type'))
                tmp_ttls     = ray.get(exec_in_pipe.remote(self.host, self.port, tmp_keyname, 'ttl'))
                tmp_idletime = ray.get(exec_in_pipe.remote(self.host, self.port, tmp_keyname, 'idletime'))
                tmp_memusage = ray.get(exec_in_pipe.remote(self.host, self.port, tmp_keyname, 'memory_usage'))
            else:
                tmp_type     = [self.conn.type(x) for x in tmp_keyname]
                tmp_ttls     = [self.conn.ttl(x) for x in tmp_keyname]
                tmp_idletime = [self.conn.object('idletime', x) for x in tmp_keyname]
                tmp_memusage = [self.conn.memory_usage(x) for x in tmp_keyname]
            return pd.DataFrame({
                'Name': tmp_keyname, 'Type': tmp_type,
                'TTLs': tmp_ttls, 'Idletime': tmp_idletime, 'MemoryUsage': tmp_memusage
            })

        elif self.redis_mode == 'cluster':
            master_keynames_df = pd.DataFrame()
            for h in self.primary_nodes:
                tmp_conn = r.Redis(h[0], h[1], socket_timeout=SOCKET_TIMEOUT, decode_responses=True)
                tmp_keyname = list(tmp_conn.scan_iter(count=SCAN_BUFFER_SIZE))
                if pipemode:
                    tmp_type     = ray.get(exec_in_pipe.remote(h[0], h[1], tmp_keyname, 'type'))
                    tmp_ttls     = ray.get(exec_in_pipe.remote(h[0], h[1], tmp_keyname, 'ttl'))
                    tmp_idletime = ray.get(exec_in_pipe.remote(h[0], h[1], tmp_keyname, 'idletime'))
                    tmp_memusage = ray.get(exec_in_pipe.remote(h[0], h[1], tmp_keyname, 'memory_usage'))
                else:
                    tmp_type     = [tmp_conn.type(x) for x in tmp_keyname]
                    tmp_ttls     = [tmp_conn.ttl(x) for x in tmp_keyname]
                    tmp_idletime = [tmp_conn.object('idletime', x) for x in tmp_keyname]
                    tmp_memusage = [tmp_conn.memory_usage(x) for x in tmp_keyname]
                node_ip = [h[0]] * len(tmp_keyname)
                tmp_keynames_df = pd.DataFrame({
                    'NodeIp': node_ip, 'Name': tmp_keyname, 'Type': tmp_type,
                    'TTLs': tmp_ttls, 'Idletime': tmp_idletime, 'MemoryUsage': tmp_memusage
                })
                tmp_conn.close()
                master_keynames_df = pd.concat([master_keynames_df, tmp_keynames_df], axis=0)
            master_keynames_df.reset_index(drop=True, inplace=True)
            master_keynames_df.astype(str)
            return master_keynames_df

    def slowlog(self):
        if self.redis_mode == 'cluster':
            slowlog_df = pd.DataFrame()
            for h in self.nodes:
                tmp_conn = r.Redis(h[0], h[1], socket_timeout=SOCKET_TIMEOUT, decode_responses=True)
                tmp_slowlog = pd.json_normalize(tmp_conn.slowlog_get(128), max_level=2, errors='ignore', sep='.')
                tmp_slowlog['node'] = h[0]
                slowlog_df = pd.concat([slowlog_df, tmp_slowlog], axis=0)
                tmp_conn.close()
            slowlog_df.reset_index(drop=True, inplace=True)
            slowlog_df = slowlog_df.astype(str)
            slowlog_df['duration_ms'] = slowlog_df['duration'].astype('int') / 1000
            slowlog_df['start_time'] = slowlog_df['start_time'].astype('int').apply(
                lambda x: datetime.utcfromtimestamp(x).strftime('%Y-%m-%d %H:%M:%S')
            )
            slowlog_df.drop('duration', axis=1, inplace=True)
            return slowlog_df[['node', 'id', 'start_time', 'duration_ms', 'command']]

        elif self.redis_mode == 'standalone':
            df = pd.json_normalize(self.conn.slowlog_get(128), max_level=2, errors='ignore', sep='.')
            df['duration_ms'] = df['duration'].astype('int') / 1000
            df.drop('duration', axis=1, inplace=True)
            df['start_time'] = df['start_time'].astype('int').apply(
                lambda x: datetime.utcfromtimestamp(x).strftime('%Y-%m-%d %H:%M:%S')
            )
            return df

    def info(self):
        if self.redis_mode == 'cluster':
            redis_info_json = []
            for h in self.nodes:
                tmp_conn = r.Redis(h[0], h[1], socket_timeout=SOCKET_TIMEOUT)
                db_info = tmp_conn.info()
                redis_info_json.append({'node': h[0], 'info': db_info})
                tmp_conn.close()
            df = pd.json_normalize(redis_info_json, max_level=3, errors='ignore', sep='.')
            df.reset_index(drop=True, inplace=True)
            return df.astype(str)

        elif self.redis_mode == 'standalone':
            info_data = self.conn.info()
            empty_dict = {}
            for k, v in info_data.items():
                if not isinstance(v, dict):
                    prefix = 'str' if isinstance(v, str) else 'num'
                    empty_dict[f'{prefix}_{k}'] = v
            return pd.json_normalize(empty_dict).T

    def check_for_traffic(self, wait_seconds=20):
        conn1 = self.conn
        data1 = conn1.info(section='commandstats')
        time.sleep(wait_seconds)
        data2 = conn1.info(section='commandstats')
        noise = ['cmdstat_ping', 'cmdstat_config', 'cmdstat_client',
                 'cmdstat_auth', 'cmdstat_info', 'cmdstat_replconf']
        df_data1 = pd.DataFrame(data1).drop(columns=noise, errors='ignore')
        df_data2 = pd.DataFrame(data2).drop(columns=noise, errors='ignore')
        df_data1.drop(['usec', 'usec_per_call'], axis=0, inplace=True, errors='ignore')
        df_data2.drop(['usec', 'usec_per_call'], axis=0, inplace=True, errors='ignore')
        conn1.close()
        return 'No traffic' if df_data1.equals(df_data2) else 'Traffic seen'
