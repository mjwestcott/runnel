import anyio
import pytest

from runnel.concurrency import WatermarkQueue


@pytest.mark.asyncio
async def test_queue():
    watermark = 8
    q = WatermarkQueue(watermark, direction="lt")

    for i in range(64):
        await q.put(i)

    passed = False
    async with anyio.move_on_after(0.01) as scope:
        await q.wait_for_watermark()
        passed = True

    assert scope.cancel_called
    assert not passed
    assert q.qsize() > watermark


@pytest.mark.asyncio
async def test_queue_with_consumer():
    watermark = 8
    q = WatermarkQueue(watermark, direction="lt")

    for i in range(64):
        await q.put(i)

    async def consumer():
        while True:
            await q.get()
            await anyio.sleep(0)

    async def waiter():
        await q.wait_for_watermark()
        assert q.qsize() <= watermark

    async with anyio.create_task_group() as tg:
        await tg.spawn(consumer)

        await waiter()
        await tg.cancel_scope.cancel()
