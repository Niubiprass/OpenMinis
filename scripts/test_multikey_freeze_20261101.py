#!/usr/bin/env python3
"""Portable concurrency MODEL + Swift source contracts, not an iOS build.
Old blocking-storage convoy is reproduced; the replacement's queue protocol
is stressed with a deliberately blocked persistence backend and concurrent
CRUD/outcomes/cursor reservations. Uses synthetic identifiers, never secrets.
"""
import threading, concurrent.futures, time, random, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODEL=(ROOT/'src/ios/Providers/ProviderMultiKeys.swift').read_text()
FACTORY=(ROOT/'src/ios/Agent/Chat/AIChatViewModel+ProviderFactory.swift').read_text()
WRAP=(ROOT/'src/ios/Providers/AgentProvider.swift').read_text()

class MemoryProtocol:
    def __init__(self):
        self.lock=threading.Lock(); self.cursor=0; self.count=0
        self.ring=['main','extra1','extra2']; self.dirty=set(); self.scheduled=False
        self.entered=threading.Event(); self.release=threading.Event()
        self.finished=threading.Event(); self.disk={}; self.worker=None
    def mark(self,domain):
        self.dirty.add(domain)
    def enqueue(self):
        with self.lock:
            if self.scheduled: return
            self.scheduled=True
        self.worker=threading.Thread(target=self.drain,daemon=True);self.worker.start()
    def drain(self):
        while True:
            with self.lock:
                domains=self.dirty;self.dirty=set()
                snapshot={'cursor':self.cursor,'count':self.count,'ring':list(self.ring)}
                if not domains:
                    self.scheduled=False;self.finished.set();return
            self.entered.set()
            if not self.release.wait(60): raise RuntimeError('test gate was not released within 60 seconds')
            for domain in domains: self.disk[domain]=snapshot[domain]
    def reserve(self,n):
        with self.lock:
            c=self.cursor;self.cursor=c+1;self.mark('cursor')
        self.enqueue();return c%n
    def outcome(self):
        with self.lock:
            self.count+=1;self.mark('count')
        self.enqueue()
    def edit(self):
        with self.lock:
            self.ring=[self.ring[0],'replacement'];self.mark('ring')
        self.enqueue()
    def read(self):
        with self.lock:return self.cursor,self.count,list(self.ring)

class Behaviour(unittest.TestCase):
    def test_old_storage_under_reader_lock_reproduces_convoy(self):
        lock=threading.Lock();entered=threading.Event();release=threading.Event();read=threading.Event()
        def old_writer():
            with lock: entered.set();release.wait(2)
        def old_reader():
            with lock:read.set()
        writer=threading.Thread(target=old_writer);writer.start();self.assertTrue(entered.wait(1))
        reader=threading.Thread(target=old_reader);reader.start()
        try:self.assertFalse(read.wait(.06))
        finally:release.set();writer.join(2);reader.join(2)
        self.assertTrue(read.is_set())
    def test_blocked_writer_does_not_block_memory_reads_or_leases(self):
        m=MemoryProtocol();self.assertEqual(m.reserve(3),0);self.assertTrue(m.entered.wait(1))
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                reads=[pool.submit(m.read) for _ in range(48)]
                picks=[pool.submit(m.reserve,3) for _ in range(240)]
                for f in reads:self.assertEqual(len(f.result(timeout=1)[2]),3)
                values=[f.result(timeout=1) for f in picks]
                self.assertEqual([values.count(i) for i in range(3)],[80,80,80])
        finally:m.release.set()
        self.assertTrue(m.finished.wait(2));self.assertEqual(m.disk['cursor'],241)
    def test_no_lost_increments_or_stale_snapshot_after_blocked_write(self):
        m=MemoryProtocol();m.outcome();self.assertTrue(m.entered.wait(1))
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures=[pool.submit(m.outcome) for _ in range(2000)]
                futures += [pool.submit(m.reserve,7) for _ in range(2000)]
                m.edit()
                for f in futures:f.result(timeout=2)
            self.assertEqual(m.read()[1],2001)
        finally:m.release.set()
        self.assertTrue(m.finished.wait(3))
        self.assertEqual(m.disk['count'],2001);self.assertEqual(m.disk['cursor'],2000)
        self.assertEqual(m.disk['ring'],['main','replacement'])
    def test_last_resort_exclusions_and_empty_ring_semantics(self):
        def pick(main,ring,enabled,excluded):
            if not enabled or not ring:return None if not main or 'main' in excluded else 'main'
            pool=[k for k,usable in [('main',False)]+ring if usable and k not in excluded]
            return pool[0] if pool else (None if not main or 'main' in excluded else 'main')
        self.assertEqual(pick(True,[],True,set()),'main')
        self.assertEqual(pick(True,[('extra1',False)],True,set()),'main')
        self.assertIsNone(pick(True,[('extra1',False)],True,{'main'}))
        self.assertEqual(pick(True,[('extra1',True)],False,set()),'main')

class SourceContracts(unittest.TestCase):
    def test_no_sync_ring_read_on_request_main_actor(self):
        self.assertNotIn('ProviderMultiKeyManager.shared.isActive(for:',FACTORY)
        self.assertNotIn('ProviderMultiKeyManager.shared.effectiveKey(for:',FACTORY)
        self.assertEqual(FACTORY.count('effectiveKeyAsync(for: instance.id)'),7)
        self.assertIn('isActiveAsync(for: instance.id)',FACTORY)
        self.assertIn('primaryKeyAsync(for: instance.id)',FACTORY)
        self.assertIn('apiKeyOverride: resolvedAPIKey',FACTORY)
    def test_lease_has_no_outer_lock_and_no_persistence(self):
        b=MODEL.split('func lease(for instanceId:',1)[1].split('private func increment',1)[0]
        self.assertNotIn('lock.lock()',b);self.assertNotIn('UserDefaults.standard',b)
        self.assertNotIn('saveMainState(',b);self.assertNotIn('writeBlob(',b)
        self.assertIn('reserveCursor(for:',b)
    def test_reservation_does_not_wait_for_storage(self):
        b=MODEL.split('private func reserveCursor(',1)[1].split('private func unlockedSave(',1)[0]
        self.assertLess(b.index('UserDefaults.standard.integer'),b.rindex('lock.lock()'))
        self.assertNotIn('.set(',b);self.assertNotIn('.sync',b)
        self.assertLess(b.rindex('lock.unlock()'),b.index('schedulePersistence(for:'))
    def test_writes_are_in_separate_writer_after_unlock(self):
        b=MODEL.split('private func persistLatest(',1)[1].split('private func setDefault(',1)[0]
        first_unlock=b.index('lock.unlock()')
        first_storage_write=min(b.index('persistRing('),b.index('persistMain('))
        self.assertLess(first_unlock,first_storage_write)
        self.assertIn('setDefault(cursor,',b)
        self.assertNotIn('recordLock',MODEL)
        self.assertIn('dirtyVersions[instanceId]?[domain] == versions[domain]',b)
        self.assertIn('dirty[instanceId]?.remove(domain)',b)
    def test_crud_and_outcomes_share_atomic_memory_mutations(self):
        self.assertGreaterEqual(MODEL.count('mutateKeys(for: instanceId)'),5)
        self.assertIn('mainSnapshots[instanceId] = state',MODEL)
        self.assertIn('list[index].updatedAt <= lease.startedAt',MODEL)
        self.assertIn('state.lastFailureAt.map({ $0 <= lease.startedAt })',MODEL)
        self.assertIn('k.unavailableUntil = nil',MODEL)
    def test_wrapper_uses_async_lease_and_preserves_failover(self):
        self.assertIn('await manager.leaseAsync(for: instanceId, excluding: attempted)',WRAP)
        self.assertIn('if exposed {',WRAP);self.assertIn('attemptedSecrets.insert(lease.key).inserted',WRAP)
        self.assertIn('keyCount * (priorityRetries + gatewayRetrySlots)',WRAP)
    def test_keychain_failure_is_not_cached_as_empty(self):
        self.assertIn('guard blob.readable else { return [] }',MODEL)
        self.assertIn('if status == errSecItemNotFound { return (nil, true) }',MODEL)
        self.assertIn('guard status == errSecSuccess',MODEL)
        self.assertIn('guard let decoded = try? JSONDecoder()',MODEL)
    def test_secrets_stay_in_local_keychain(self):
        self.assertIn('kSecAttrSynchronizable as String: false',MODEL)
        output_calls=[line for line in MODEL.splitlines() if line.lstrip().startswith(('print(', 'dump(', 'debugPrint('))]
        log_calls=[line for line in MODEL.splitlines() if line.lstrip().startswith(('logger.', 'AppLogger('))]
        self.assertEqual(output_calls,[])
        self.assertEqual(log_calls,[])

if __name__=='__main__':unittest.main(verbosity=2)
