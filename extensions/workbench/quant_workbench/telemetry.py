"""Bounded process-local HTTP observations, with explicit coverage boundaries."""
from collections import deque
from datetime import datetime, timezone
import time
import threading


class RequestTelemetry:
    def __init__(self):
        self.started=time.time()
        self.samples=deque(maxlen=10000)
        self.lock=threading.Lock()
        self.evicted_at=None

    def record(self,status,duration):
        with self.lock:
            if len(self.samples)==self.samples.maxlen:self.evicted_at=self.samples[0][0]
            self.samples.append((time.time(),status,duration))

    def snapshot(self):
        now=time.time()
        with self.lock:
            rows=[r for r in self.samples if r[0]>=now-300]
            truncated=self.evicted_at is not None and self.evicted_at>=now-300
        total=len(rows); errors=sum(r[1]>=500 for r in rows); client=sum(400<=r[1]<500 for r in rows)
        durations=sorted(r[2] for r in rows)
        return {'availability':'available' if total else 'empty','window_seconds':300,
                'completed_requests':total,'server_errors':errors,'client_errors':client,
                'error_rate':errors/total if total else None,
                'p95_ms':durations[min(len(rows)-1,int(len(rows)*.95))] if rows else None,
                'coverage_seconds':min(300,max(0,now-self.started)), 'truncated':truncated,
                'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),
                'collection_started_at':datetime.fromtimestamp(self.started,timezone.utc).isoformat(),
                'scope':'当前服务进程；排除静态资源、健康检查和遥测轮询；重启后重新累计。容量上限10000条。'}
