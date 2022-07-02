
# pip install ipcalc plotly pandasql ray pyarrow fastparquet 

import ray 
import io
import requests
import json 
import ipcalc 
from datetime import datetime
import plotly.express as px # pip install plotly-express

ray.init(ignore_reinit_error=True)

PIPE_BUFFER_SIZE= 10_000
SCAN_BUFFER_SIZE=500_000
SOCKET_TIMEOUT  =     10      # in seconds


def resolve_ip(ip):
    try:
        hostname=socket.gethostbyaddr(ip)[0]
        return hostname
    except socket.herror as e:
        return ip

@ray.remote
def exec_in_pipe(hostname,port,key_list,cmd,batch_size=PIPE_BUFFER_SIZE):
    conn=r.Redis(host=hostname,port=port,socket_timeout=SOCKET_TIMEOUT,decode_responses=True)
    pipe=conn.pipeline(transaction=False)
    full_result=[]
    while(len(key_list)>0):
      list1=key_list[:batch_size]
      if cmd=='idletime':
          for key in list1:
            exec(f"""
pipe.object("idletime",'{key}')
            """)
          result=pipe.execute()
          full_result=full_result+result
          key_list=key_list[batch_size:]
      else:
          for key in list1:
            # exec("pipe."+cmd+"('"+key+"')")
            exec(f"""
pipe.{cmd}('{key}')
                 """)
          result=pipe.execute()
          #print(len(full_result))
          full_result=full_result+result
          key_list=key_list[batch_size:]
    pipe.close()
    return full_result


import socket
import redis as r
import numpy as np
import time 
import pandas as pd 
import pandasql as ps  



pd.set_option('display.max_colwidth', 500)
pd.set_option("display.max_columns", 500)
pd.options.display.max_rows = 500


class RedisDB:
  def __init__(self,host,port=6379):
    self.host=host
    self.port=port
    self.conn=r.Redis(host,port,socket_timeout=SOCKET_TIMEOUT,decode_responses=True)
    self.redis_mode=self.conn.info()['redis_mode']
    if(self.redis_mode=='cluster'):
        primary_nodes=[]
        replica_nodes=[]
        nodes_dict=self.conn.cluster('nodes')
        for ids in list(nodes_dict):
            if "master" in nodes_dict[ids]["flags"]:
                primary_nodes.append(ids.split("@")[0].split(":"))
            if "slave" in nodes_dict[ids]["flags"]:
                replica_nodes.append(ids.split("@")[0].split(":"))
        self.primary_nodes=primary_nodes
        self.replica_nodes=replica_nodes
        self.nodes=primary_nodes + replica_nodes
    
  def keyspace(self):
    if(self.redis_mode=='standalone'):
        conn1=r.Redis(self.host,self.port,socket_timeout=SOCKET_TIMEOUT)
        keyspace=[conn1.info()[db]['keys'] for db in [ x for x in list(conn1.info().keys()) if x.startswith('db') ] ]
        df=pd.DataFrame([(self.host,self.port,str(len(keyspace)),str(np.array(keyspace).sum()))],columns=['Hostname','Port','#dbs','#keys'])
        #df.reset_index(drop=True, inplace=True)
        return df
    elif(self.redis_mode=='cluster'):
        master_keynames_df=pd.DataFrame()
        output_list=[]
        for h in self.primary_nodes:
            conn1=r.Redis(h[0],h[1],socket_timeout=10)
            keyspace=[conn1.info()[db]['keys'] for db in [ x for x in list(conn1.info().keys()) if x.startswith('db') ] ]
            output_list.append((h[0],h[1],str(len(keyspace)),str(np.array(keyspace).sum())))
            conn1.close() 
        df=pd.DataFrame(output_list,columns=['Hostname','Port','#dbs','#keys'])
        #df.reset_index(drop=True, inplace=True)
        return df

  def supported_commands(self):
    conn1=r.Redis(self.host,self.port,socket_timeout=SOCKET_TIMEOUT)
    data=conn1.command()
    row=[data[x] for x in data]
    return pd.json_normalize(row)   

            
  def client_list(self):
    if(self.redis_mode=='standalone'):
        conn=self.conn
        df=pd.DataFrame(conn.client_list())
        return df
    elif(self.redis_mode=='cluster'):
        master_df=pd.DataFrame()
        for h in self.primary_nodes:
            # print(h[0])
            tmp_conn=r.Redis(h[0],h[1],socket_timeout=SOCKET_TIMEOUT)
            df=pd.DataFrame(tmp_conn.client_list())
            tmp_conn.close()
            df["node"]=f"{h[0]}:{h[1]}"
            master_df=pd.concat([master_df,df], axis=0)
            # print(h[0],master_df.shape)
        master_df.reset_index(drop=True,inplace=True)
#         master_df["age"]=pd.to_timedelta(master_df['age'], unit='s')
#         master_df["idle"]=pd.to_timedelta(master_df['idle'], unit='s')
        master_df.astype(str)
#         def highlight_cells(val, color_if_true, color_if_false):
#             color = color_if_true if val != "0" else color_if_false
#             return 'background-color: {}'.format(color)
#         return master_df.style.applymap(highlight_cells, color_if_true='yellow', color_if_false='#C6E2E9', 
#                   subset=['qbuf', 'qbuf-free'])  
        return master_df
        
  def client_hosts(self):
    if(self.redis_mode=='standalone'):
        conn=self.conn
        for x in list(set([ x.split(':')[0]  for x in list(pd.DataFrame(conn.client_list())['addr']) ])):
          ip_subnet=query_ip(x) 
          print(x,ip_subnet)

  def scankeys(self,pipemode = True):
    if(self.redis_mode=='standalone'):
        tmp_keyname=[ x for x in self.conn.scan_iter(count=SCAN_BUFFER_SIZE)]
        if(pipemode==True):
            tmp_type_obj=exec_in_pipe.remote(self.host,self.port,tmp_keyname,"type")
            tmp_ttls_obj=exec_in_pipe.remote(self.host,self.port,tmp_keyname,"ttl")
            tmp_idletime_obj=exec_in_pipe.remote(self.host,self.port,tmp_keyname,"idletime")
            tmp_memusage_obj=exec_in_pipe.remote(self.host,self.port,tmp_keyname,"memory_usage")

            tmp_type=ray.get(tmp_type_obj)
            tmp_ttls=ray.get(tmp_ttls_obj)
            tmp_idletime=ray.get(tmp_idletime_obj)
            tmp_memusage=ray.get(tmp_memusage_obj)

        elif(pipemode==False):
            tmp_type=[ self.conn.type(x) for x in tmp_keyname]
            tmp_ttls=[ self.conn.ttl(x) for x in tmp_keyname]
            tmp_idletime=[ self.conn.object("idletime",x) for x in tmp_keyname]
            tmp_memusage=[ self.conn.memory_usage(x) for x in tmp_keyname]        
        #tmp_type=[ x.decode("utf8") for x in tmp_type ]
        keynames_df=pd.DataFrame({"Name": tmp_keyname,"Type": tmp_type, "TTLs": tmp_ttls, "Idletime": tmp_idletime, "MemoryUsage": tmp_memusage})
        return keynames_df
    elif(self.redis_mode=='cluster'):
        master_keynames_df=pd.DataFrame()
        for h in self.primary_nodes:
            tmp_conn=r.Redis(h[0],h[1],socket_timeout=SOCKET_TIMEOUT,decode_responses=True)
            tmp_keyname=[ x for x in tmp_conn.scan_iter(count=SCAN_BUFFER_SIZE)]

            if(pipemode==True):
                tmp_type_obj=exec_in_pipe.remote(h[0],h[1],tmp_keyname,"type")
                tmp_ttls_obj=exec_in_pipe.remote(h[0],h[1],tmp_keyname,"ttl")
                tmp_idletime_obj=exec_in_pipe.remote(h[0],h[1],tmp_keyname,"idletime")
                tmp_memusage_obj=exec_in_pipe.remote(h[0],h[1],tmp_keyname,"memory_usage")
                
                tmp_type=ray.get(tmp_type_obj)
                tmp_ttls=ray.get(tmp_ttls_obj)
                tmp_idletime=ray.get(tmp_idletime_obj)
                tmp_memusage=ray.get(tmp_memusage_obj)
                
            elif(pipemode==False):
                tmp_type=[ tmp_conn.type(x) for x in tmp_type]
                tmp_ttls=[ tmp_conn.ttl(x) for x in tmp_keyname]
                tmp_idletime=[ tmp_conn.object("idletime",x) for x in tmp_keyname]
                tmp_memusage=[ tmp_conn.memory_usage(x) for x in tmp_keyname]
            
            #tmp_type=[ x.decode("utf8") for x in tmp_type ]
            node_ip=[ h[0] for x in range(len(tmp_keyname))]
            #if any( [ len(tmp_keyname) != len(tmp_type), len(tmp_keyname) != len(tmp_ttls), len(tmp_keyname) != len(tmp_idletime), len(tmp_keyname) != len(tmp_memusage)] ):
            #print(len(tmp_keyname),len(tmp_type),len(tmp_ttls),len(tmp_idletime),len(tmp_memusage))
            tmp_keynames_df=pd.DataFrame({"NodeIp": node_ip,"Name": tmp_keyname,"Type": tmp_type, "TTLs": tmp_ttls, "Idletime": tmp_idletime, "MemoryUsage": tmp_memusage})
            tmp_conn.close()
            master_keynames_df=pd.concat([master_keynames_df,tmp_keynames_df], axis=0)
        master_keynames_df.reset_index(drop=True,inplace=True)
        master_keynames_df.astype(str)
        return master_keynames_df

  def slowlog(self):
    if(self.redis_mode=='cluster'):
        #slowlog_df=pd.DataFrame(columns=['node','id','start_time','duration','command'],dtype=['str','str','str','str','str'])
        slowlog_df=pd.DataFrame()
        for h in self.nodes:
            tmp_conn=r.Redis(h[0],h[1],socket_timeout=SOCKET_TIMEOUT,decode_responses=True)
            tmp_slowlog=pd.json_normalize(tmp_conn.slowlog_get(128), max_level=2,errors='ignore',sep='.')
            tmp_slowlog['node']=h[0]
            slowlog_df=pd.concat([slowlog_df, tmp_slowlog], axis=0)
            tmp_conn.close()
        # df=pd.json_normalize(redis_info_json, max_level=3,errors='ignore',sep='.')
        slowlog_df.reset_index(drop=True,inplace=True)
        slowlog_df=slowlog_df.astype(str)
        #final_df=df[['node','info.maxmemory','info.used_memory','info.used_memory_peak','info.uptime_in_days']]
        slowlog_df['duration_ms']=slowlog_df['duration'].astype('int')/1000 
        slowlog_df['start_time']=slowlog_df['start_time'].astype('int').apply(lambda x: datetime.utcfromtimestamp(x).strftime('%Y-%m-%d %H:%M:%S'))
        #slowlog_df['command']=slowlog_df['command'].apply(lambda x: x[2:-1])
        slowlog_df.drop('duration',axis=1,inplace=True)
        # ps.sqldf("  select * from slowlog_df where command not like '%nodes%' and command not like '%info%' and command not like '%cluster%' and command not like '%slowlog%'  order by start_time desc")
        return slowlog_df[['node','id','start_time','duration_ms','command']]
    elif(self.redis_mode=='standalone'):
        tmp_conn=r.Redis(self.host,self.port,socket_timeout=SOCKET_TIMEOUT,decode_responses=True)
        df=pd.json_normalize(self.conn.slowlog_get(128), max_level=2,errors='ignore',sep='.')
        #df['command']=df['command'].apply(lambda x: x[2:-1])
        df['duration_ms']=df['duration'].astype('int')/1000 
        df.drop('duration',axis=1,inplace=True)
        df['start_time']=df['start_time'].astype('int').apply(lambda x: datetime.utcfromtimestamp(x).strftime('%Y-%m-%d %H:%M:%S'))
        tmp_conn.close()
        return df
        
  def info(self):
    if(self.redis_mode=='cluster'):
        redis_info_json=[]
        for h in self.nodes:
            tmp_conn=r.Redis(h[0],h[1],socket_timeout=SOCKET_TIMEOUT)
            db_info=tmp_conn.info()
            db_info_json= { "node": h[0], "info": db_info }
            redis_info_json.append(db_info_json)
            tmp_conn.close()
        df=pd.json_normalize(redis_info_json, max_level=3,errors='ignore',sep='.')
        df.reset_index(drop=True,inplace=True)
        df=df.astype(str)
        #final_df=df[['node','info.maxmemory','info.used_memory','info.used_memory_peak','info.uptime_in_days']]
        return df
    elif(self.redis_mode=='standalone'):
        info_data=self.conn.info()
        empty_dict={}
        for k,v in info_data.items():
            if(not isinstance(v,dict)):
                if(isinstance(v,str)):
                    k1=f"str_{k}"
                    empty_dict.update({k1: v})
                else:
                    k1=f"num_{k}"
                    empty_dict.update({k1: v})
        return pd.json_normalize(empty_dict).T

  def check_for_traffic(self,wait_seconds=20):
    conn1=self.conn
    data1=conn1.info(section='commandstats')
    time.sleep(wait_seconds)
    data2=conn1.info(section='commandstats')
    df_data1=pd.DataFrame(data1)
    df_data2=pd.DataFrame(data2)
    conn1.close()
    df_data1.drop(['cmdstat_ping','cmdstat_config','cmdstat_client','cmdstat_auth','cmdstat_info','cmdstat_replconf'],axis=1,inplace=True,errors='ignore')
    df_data2.drop(['cmdstat_ping','cmdstat_config','cmdstat_client','cmdstat_auth','cmdstat_info','cmdstat_replconf'],axis=1,inplace=True,errors='ignore')
    df_data1.drop(['usec','usec_per_call'],axis=0,inplace=True,errors='ignore')
    df_data2.drop(['usec','usec_per_call'],axis=0,inplace=True,errors='ignore')

    if(df_data1.equals(df_data2)):
        return 'No traffic'
    else:
        return 'Traffic seen'
