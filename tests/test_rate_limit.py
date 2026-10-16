import unittest
from types import SimpleNamespace as NS
from progressor_core.rate_limit import SlidingWindows, client_address


class BoundedWindows(unittest.TestCase):
    def test_window_and_independent_identities(self):
        rate = SlidingWindows(capacity=3)
        self.assertTrue(rate.allow('a', 2, now=0))
        self.assertTrue(rate.allow('a', 2, now=1))
        self.assertFalse(rate.allow('a', 2, now=59))
        self.assertTrue(rate.allow('b', 2, now=59))
        self.assertTrue(rate.allow('a', 2, now=60))
        self.assertFalse(rate.allow('a', 2, now=60))

    def test_many_identities_have_bounded_memory_without_resetting_active_quota(self):
        rate = SlidingWindows(capacity=4)
        for i in range(4): self.assertTrue(rate.allow(str(i), 1, now=0))
        for i in range(4, 10000): self.assertFalse(rate.allow(str(i), 1, now=1))
        self.assertEqual(len(rate.buckets), 4)
        self.assertFalse(rate.allow('0', 1, now=2))
        self.assertTrue(rate.allow('new', 1, now=62))
        self.assertEqual(len(rate.buckets), 1)

    def test_header_only_from_loopback_and_only_valid_ip(self):
        def request(host, header): return NS(client=NS(host=host), headers={'X-Real-IP':header})
        self.assertEqual(client_address(request('127.0.0.1', '2001:0db8::1')), '2001:db8::1')
        self.assertEqual(client_address(request('127.0.0.1', 'arbitrary '*2000)), '127.0.0.1')
        self.assertEqual(client_address(request('203.0.113.1', '198.51.100.1')), '203.0.113.1')
