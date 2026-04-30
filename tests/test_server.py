"""Unit tests for server-level primitives that don't need the FastAPI app.

The bulk of server.py is exercised through the route-level tests in
test_admin.py, test_matches.py, etc. This file targets a few in-process
primitives that don't have a natural HTTP entry point — mainly the
ResizableSemaphore, whose live-resize behavior is documented as an
invariant in CLAUDE.md but had no direct test.
"""

from __future__ import annotations

import asyncio

import pytest

from server import ResizableSemaphore


@pytest.mark.asyncio
async def test_basic_acquire_and_release():
    sem = ResizableSemaphore(2)
    await sem.acquire()
    await sem.acquire()
    # Both slots taken — a third acquire must block.
    blocked = asyncio.create_task(sem.acquire())
    await asyncio.sleep(0.01)
    assert not blocked.done()
    sem.release()
    # Releasing one slot lets the third acquire proceed.
    await asyncio.wait_for(blocked, timeout=1.0)
    assert sem.limit == 2


@pytest.mark.asyncio
async def test_async_context_manager_releases_on_exit():
    sem = ResizableSemaphore(1)
    async with sem:
        # Inside the block, capacity is exhausted.
        blocked = asyncio.create_task(sem.acquire())
        await asyncio.sleep(0.01)
        assert not blocked.done()
    # After the block, the slot is back; the waiter completes.
    await asyncio.wait_for(blocked, timeout=1.0)


@pytest.mark.asyncio
async def test_resize_grows_capacity_releases_waiters():
    sem = ResizableSemaphore(1)
    await sem.acquire()  # capacity exhausted
    waiter1 = asyncio.create_task(sem.acquire())
    waiter2 = asyncio.create_task(sem.acquire())
    await asyncio.sleep(0.01)
    assert not waiter1.done()
    assert not waiter2.done()

    await sem.resize(3)
    # Growing by +2 must let both waiters proceed without anyone releasing.
    await asyncio.wait_for(asyncio.gather(waiter1, waiter2), timeout=1.0)
    assert sem.limit == 3


@pytest.mark.asyncio
async def test_resize_shrink_absorbs_releases():
    sem = ResizableSemaphore(3)
    await sem.acquire()
    await sem.acquire()
    await sem.acquire()  # 3 in flight

    await sem.resize(1)
    # Two of the three pending releases should be swallowed; one should
    # restore capacity to the new limit of 1.
    sem.release()
    sem.release()
    sem.release()

    # New acquires past the new limit must block.
    await sem.acquire()  # consumes the only available slot
    blocked = asyncio.create_task(sem.acquire())
    await asyncio.sleep(0.01)
    assert not blocked.done()
    sem.release()
    await asyncio.wait_for(blocked, timeout=1.0)
    assert sem.limit == 1


@pytest.mark.asyncio
async def test_resize_to_same_value_is_noop():
    sem = ResizableSemaphore(2)
    await sem.acquire()
    await sem.resize(2)
    # Still one slot left — second acquire should not block.
    await asyncio.wait_for(sem.acquire(), timeout=0.5)
    assert sem.limit == 2


@pytest.mark.asyncio
async def test_resize_floors_at_one():
    sem = ResizableSemaphore(2)
    await sem.resize(0)
    # Min limit is 1, not 0 — a single concurrent holder still works.
    assert sem.limit == 1
    await asyncio.wait_for(sem.acquire(), timeout=0.5)
    sem.release()


@pytest.mark.asyncio
async def test_constructor_floors_at_one():
    sem = ResizableSemaphore(0)
    assert sem.limit == 1
    sem_neg = ResizableSemaphore(-5)
    assert sem_neg.limit == 1


@pytest.mark.asyncio
async def test_inflight_holders_complete_normally_after_shrink():
    """Documented invariant from server.py: shrinking never disturbs in-flight
    work — the holders finish, their releases get absorbed by shrink_debt."""
    sem = ResizableSemaphore(3)
    holders_done = []

    async def hold():
        await sem.acquire()
        await asyncio.sleep(0.05)
        sem.release()
        holders_done.append(True)

    tasks = [asyncio.create_task(hold()) for _ in range(3)]
    await asyncio.sleep(0.01)
    await sem.resize(1)
    await asyncio.gather(*tasks)
    assert len(holders_done) == 3
    assert sem.limit == 1
