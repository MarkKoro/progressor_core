"""Bounded in-process sliding windows. Unknown identities cannot grow memory forever."""
import ipaddress
import time
from collections import OrderedDict, deque


class SlidingWindows:
    def __init__(self, capacity=4096, window=60):
        self.capacity, self.window = capacity, window
        self.buckets = OrderedDict()

    def allow(self, key, limit, *, now=None):
        stamp = time.monotonic() if now is None else now
        cutoff = stamp - self.window
        # Most recent accepted request is at the end. Expired identities are removed as a
        # whole; active identities are never evicted to reset their quota.
        while self.buckets and next(iter(self.buckets.values()))[-1] <= cutoff:
            self.buckets.popitem(last=False)
        bucket = self.buckets.get(key)
        if bucket is None:
            if len(self.buckets) >= self.capacity: return False
            bucket = deque()
            self.buckets[key] = bucket
        while bucket and bucket[0] <= cutoff: bucket.popleft()
        if len(bucket) >= limit: return False
        bucket.append(stamp)
        self.buckets.move_to_end(key)
        return True


def client_address(request):
    address = request.client.host if request.client else 'unknown'
    if address in ('127.0.0.1', '::1'):
        try: return str(ipaddress.ip_address(request.headers.get('X-Real-IP', address)))
        except ValueError: pass
    return address
