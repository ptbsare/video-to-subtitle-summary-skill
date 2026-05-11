#!/usr/bin/env python3
"""
Test script for the MCP server (async task version).
Tests the underlying logic directly rather than going through MCP protocol.
"""

import asyncio
import json
import re
import sys
import tempfile
import time
from pathlib import Path

# Add the skill directory to Python path
skill_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(skill_dir))

from mcp_server import (
    TaskStore,
    TaskRecord,
    TaskStatus,
    _format_task_response,
    _STAGES,
    task_store,
    _handle_submit,
    _handle_query,
)


async def test_task_store_basic():
    """Test basic task store operations."""
    print("=" * 60)
    print("Test 1: Task store basic operations")

    store = TaskStore(ttl=999, sweep_interval=999)

    # Create task
    tid = await store.create_task("https://example.com/video", None)
    assert len(tid) == 12, f"Expected 12-char task_id, got {len(tid)}"
    print(f"  Created task: {tid}")

    # Get task (should be pending)
    t = await store.get_task(tid)
    assert t is not None, "Task should exist"
    assert t.status == TaskStatus.PENDING
    print(f"  Status: {t.status}, stage: {t.stage}")

    # Mark processing
    await store.mark_processing(tid)
    t = await store.get_task(tid)
    assert t.status == TaskStatus.PROCESSING
    print(f"  After mark_processing: {t.status}")

    # Update progress
    store.update_progress(tid, "downloading", "下载视频")
    t = await store.get_task(tid)
    assert t.stage == "downloading"
    assert t.stage_detail == "下载视频"
    assert t.percent > 0
    print(f"  After update_progress: stage={t.stage}, percent={t.percent}%")

    # Complete task
    result_data = {
        "video_info": {"platform": "测试", "title": "测试视频", "author": "测试者"},
        "text_content": "这是测试字幕文本",
        "output_dir": "/tmp/test",
        "srt_path": "/tmp/test/subtitle.srt",
        "text_path": "/tmp/test/text.txt",
    }
    store.complete_task(tid, result_data)
    t = await store.get_task(tid)
    assert t.status == TaskStatus.COMPLETED
    assert t.percent == 100
    assert t.result == result_data
    print(f"  After complete: {t.status}, percent={t.percent}%")

    print("✅ Task store basic operations passed\n")


async def test_task_store_fail():
    """Test task failure path."""
    print("=" * 60)
    print("Test 2: Task failure")

    store = TaskStore(ttl=999, sweep_interval=999)
    tid = await store.create_task("test", None)
    await store.mark_processing(tid)

    store.fail_task(tid, "Something went wrong")
    t = await store.get_task(tid)
    assert t.status == TaskStatus.FAILED
    assert t.error == "Something went wrong"
    print(f"  Status: {t.status}, error: {t.error}")
    print("✅ Task failure handling passed\n")


async def test_task_store_expiry():
    """Test TTL expiry."""
    print("=" * 60)
    print("Test 3: TTL expiry")

    store = TaskStore(ttl=1, sweep_interval=999)  # 1 second TTL
    tid = await store.create_task("test", None)

    # Manually set completed with old timestamp
    rec = store._tasks[tid]
    rec.status = TaskStatus.COMPLETED
    rec.result = {"text_content": "test"}
    rec.updated_at = time.time() - 2  # 2 seconds ago

    t = await store.get_task(tid)
    assert t.status == TaskStatus.EXPIRED, f"Expected EXPIRED, got {t.status}"
    print(f"  Status after TTL: {t.status}")

    # Test sweep removes it
    await store.sweep_expired()
    t = await store.get_task(tid)
    assert t is None, "Expired task should be swept"
    print("  Sweep removed expired task")
    print("✅ TTL expiry passed\n")


async def test_task_store_not_found():
    """Test querying non-existent task."""
    print("=" * 60)
    print("Test 4: Non-existent task")

    store = TaskStore(ttl=999, sweep_interval=999)
    t = await store.get_task("nonexistent")
    assert t is None
    print("✅ Non-existent task returns None\n")


async def test_format_response_completed():
    """Test formatting a completed task response."""
    print("=" * 60)
    print("Test 5: Format completed task response")

    result_data = {
        "video_info": {"platform": "B站", "title": "测试视频标题", "author": "UP主"},
        "text_content": "这是一段测试字幕文本。" * 10,
        "output_dir": "/tmp/video_analysis/test123",
        "srt_path": "/tmp/video_analysis/test123/subtitle.srt",
        "text_path": "/tmp/video_analysis/test123/text.txt",
    }
    t = TaskRecord(
        task_id="abc123def456",
        status=TaskStatus.COMPLETED,
        created_at=time.time(),
        updated_at=time.time(),
        stage="completed",
        percent=100,
        result=result_data,
    )
    text = _format_task_response(t)
    assert "已完成" in text
    assert "B站" in text
    assert "测试视频标题" in text
    assert "字幕文本" in text
    assert "abc123def456" in text
    print(text)
    print("✅ Format completed response passed\n")


async def test_format_response_failed():
    """Test formatting a failed task response."""
    print("=" * 60)
    print("Test 6: Format failed task response")

    t = TaskRecord(
        task_id="xyz789",
        status=TaskStatus.FAILED,
        created_at=time.time(),
        updated_at=time.time(),
        stage="failed",
        error="缺少依赖: ffmpeg",
    )
    text = _format_task_response(t)
    assert "失败" in text
    assert "ffmpeg" in text
    print(text)
    print("✅ Format failed response passed\n")


async def test_format_response_processing():
    """Test formatting a processing task response."""
    print("=" * 60)
    print("Test 7: Format processing task response")

    t = TaskRecord(
        task_id="proc123",
        status=TaskStatus.PROCESSING,
        created_at=time.time(),
        updated_at=time.time(),
        stage="downloading",
        stage_detail="下载抖音视频",
        percent=33,
    )
    text = _format_task_response(t)
    assert "处理中" in text
    assert "downloading" in text
    assert "33%" in text
    print(text)
    print("✅ Format processing response passed\n")


async def test_format_response_expired():
    """Test formatting an expired task response."""
    print("=" * 60)
    print("Test 8: Format expired task response")

    t = TaskRecord(
        task_id="exp456",
        status=TaskStatus.EXPIRED,
        created_at=time.time() - 7200,
        updated_at=time.time() - 7200,
    )
    text = _format_task_response(t)
    assert "已过期" in text or "过期" in text
    print(text)
    print("✅ Format expired response passed\n")


async def test_handle_submit_errors():
    """Test _handle_submit error cases."""
    print("=" * 60)
    print("Test 9: _handle_submit error handling")

    # Missing input
    result = await _handle_submit({})
    assert "Error" in result[0].text
    print(f"  Missing input: {result[0].text[:80]}")

    # Non-existent file
    result = await _handle_submit({"input": "/nonexistent/video.mp4"})
    assert "Error" in result[0].text
    print(f"  Non-existent: {result[0].text[:80]}")

    print("✅ Submit error handling passed\n")


async def test_handle_query_errors():
    """Test _handle_query error cases."""
    print("=" * 60)
    print("Test 10: _handle_query error handling")

    # Missing task_id
    result = await _handle_query({})
    assert "Error" in result[0].text
    print(f"  Missing task_id: {result[0].text[:80]}")

    # Invalid task_id
    result = await _handle_query({"task_id": "nonexistent"})
    assert "Error" in result[0].text or "未找到" in result[0].text
    print(f"  Invalid task_id: {result[0].text[:80]}")

    print("✅ Query error handling passed\n")


async def test_submit_and_query_flow():
    """Test full submit → query flow with a dummy file."""
    print("=" * 60)
    print("Test 11: Full submit → query flow")

    # Create a dummy .mp4 so detect_input passes
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        dummy_path = f.name

    try:
        # Submit
        result = await _handle_submit({"input": dummy_path})
        submit_text = result[0].text
        print(f"  Submit:\n{submit_text}")

        # Extract task_id
        m = re.search(r'`([a-f0-9]{12})`', submit_text)
        assert m, f"Could not extract task_id from: {submit_text}"
        task_id = m.group(1)

        # Query (task is running in background, might be processing or failed)
        result = await _handle_query({"task_id": task_id})
        query_text = result[0].text
        print(f"  Query:\n{query_text[:300]}")

        # Verify task exists in store
        t = await task_store.get_task(task_id)
        assert t is not None
        print(f"  Task status: {t.status}, stage: {t.stage}")

        # Wait a bit for background task to finish (it will fail on missing deps)
        await asyncio.sleep(2)

        result = await _handle_query({"task_id": task_id})
        final_text = result[0].text
        print(f"  Final query:\n{final_text[:300]}")

        print("✅ Full flow passed\n")
    finally:
        Path(dummy_path).unlink(missing_ok=True)


async def test_stages_count():
    """Verify all pipeline stages are defined."""
    print("=" * 60)
    print("Test 12: Pipeline stages")

    expected = ["validating", "fetching_info", "downloading", "extracting_audio", "transcribing", "finalizing"]
    assert _STAGES == expected, f"Expected {expected}, got {_STAGES}"
    print(f"  Stages: {_STAGES}")
    print("✅ Stages verified\n")


async def run_all():
    await test_stages_count()
    await test_task_store_basic()
    await test_task_store_fail()
    await test_task_store_expiry()
    await test_task_store_not_found()
    await test_format_response_completed()
    await test_format_response_failed()
    await test_format_response_processing()
    await test_format_response_expired()
    await test_handle_submit_errors()
    await test_handle_query_errors()
    await test_submit_and_query_flow()

    print("=" * 60)
    print("🎉 All tests passed!")


if __name__ == "__main__":
    asyncio.run(run_all())
