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


# ---------------------------------------------------------------------------
# Dev-only static-asset import rewriter (REPLAY_DEV=1)
# ---------------------------------------------------------------------------

def test_rewrite_dev_imports_adds_version_to_relative_imports(tmp_path, monkeypatch):
    """When the gate is on, `import './js/foo.js'` becomes `?v=<mtime_ns>`.

    Without the rewrite, a soft refresh after editing js/coaching.js still
    serves the cached body because the import URL never changes. The dev gate
    flips the URL on every save so the browser is forced to refetch.
    """
    import server

    # Set up a tiny fake static tree: script.js + js/foo.js
    static_root = tmp_path / "static"
    js_dir = static_root / "js"
    js_dir.mkdir(parents=True)
    foo = js_dir / "foo.js"
    foo.write_text("export const x = 1;\n")
    script = static_root / "script.js"
    script.write_text(
        "import { x } from './js/foo.js';\n"
        "import { y } from './js/bar.js';\n"  # bar doesn't exist; should be left alone
        "console.log(x);\n"
    )

    monkeypatch.setattr(server, "STATIC_DIR", static_root)
    body = script.read_bytes()
    rewritten = server._rewrite_dev_imports(script, body).decode()

    assert "./js/foo.js?v=" in rewritten
    # Bar doesn't exist on disk so the rewriter leaves the import untouched
    # (returning the original match unchanged is the safe default — an
    # accidentally-broken import shouldn't be hidden by a fake `?v=0`).
    assert "./js/bar.js'" in rewritten


def test_rewrite_dev_imports_refuses_paths_outside_static_root(tmp_path, monkeypatch):
    """The rewriter must not version imports that escape STATIC_DIR — such
    imports stay literal so the browser sees the same 404 it would normally,
    rather than being hidden behind a misleading versioned URL."""
    import server

    static_root = tmp_path / "static"
    static_root.mkdir()
    outside = tmp_path / "secret.js"
    outside.write_text("// escaped")
    script = static_root / "script.js"
    script.write_text("import { x } from './js/../../secret.js';\n")

    monkeypatch.setattr(server, "STATIC_DIR", static_root)
    rewritten = server._rewrite_dev_imports(script, script.read_bytes()).decode()
    # Original import preserved (no version), so the path-traversal guard in
    # the static_file route can still reject it with the normal 400.
    assert "?v=" not in rewritten
