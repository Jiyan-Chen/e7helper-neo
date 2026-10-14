import logging
import threading
import time

from e7helper.core.events import EventBus, LogBridge, Topic


def _wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_sync_subscribe_and_unsubscribe():
    bus = EventBus()
    got = []
    sub = bus.subscribe("a", lambda e: got.append(e.data))
    bus.publish("a", 1)
    bus.publish("b", 2)
    sub.unsubscribe()
    bus.publish("a", 3)
    assert got == [1]
    assert not bus.has_subscribers("a")


def test_wildcard_receives_all_topics():
    bus = EventBus()
    got = []
    bus.subscribe("*", lambda e: got.append((e.topic, e.data)))
    bus.publish("a", 1)
    bus.publish("b", 2)
    assert got == [("a", 1), ("b", 2)]
    assert bus.has_subscribers("anything")


def test_subscriber_error_is_isolated(caplog):
    bus = EventBus()
    got = []

    def bad(e):
        raise ValueError("boom")

    bus.subscribe("a", bad)
    bus.subscribe("a", lambda e: got.append(e.data))
    with caplog.at_level(logging.ERROR):
        bus.publish("a", 1)
    assert got == [1]
    assert any("boom" in (r.exc_text or "") or r.exc_info for r in caplog.records)


def test_threaded_subscriber_does_not_block_publisher_and_keeps_latest():
    bus = EventBus()
    release = threading.Event()
    got = []

    def slow(e):
        release.wait(2)
        got.append(e.data)

    sub = bus.subscribe(Topic.FRAME, slow, threaded=True, maxsize=1)
    t0 = time.perf_counter()
    for i in range(10):
        bus.publish(Topic.FRAME, i)
    assert time.perf_counter() - t0 < 0.5  # 发布者没有被慢订阅者拖住
    release.set()
    assert _wait_for(lambda: got and got[-1] == 9)
    # 第 0 帧可能已被工作线程取走，其余中间帧被丢弃，只保留最新的
    assert len(got) <= 2
    assert sub.dropped >= 7
    bus.close()


def test_threaded_subscriber_runs_in_other_thread():
    bus = EventBus()
    threads = []
    bus.subscribe("a", lambda e: threads.append(threading.current_thread().name), threaded=True, name="x")
    bus.publish("a")
    assert _wait_for(lambda: threads)
    assert threads[0] == "events:x"
    bus.close()


def test_log_bridge_publishes_and_guards_recursion():
    bus = EventBus()
    logger = logging.getLogger("test.bridge")
    logger.setLevel(logging.INFO)
    bridge = LogBridge(bus)
    logger.addHandler(bridge)
    got = []

    def on_log(e):
        got.append(e.data["message"])
        logger.info("在订阅者里又写日志")  # 不能无限递归

    bus.subscribe(Topic.LOG, on_log)
    try:
        logger.info("你好 %d", 1)
    finally:
        logger.removeHandler(bridge)
    assert got == ["你好 1"]


def test_close_stops_workers():
    bus = EventBus()
    sub = bus.subscribe("a", lambda e: None, threaded=True)
    worker_thread = sub._worker.thread
    bus.close()
    worker_thread.join(1)
    assert not worker_thread.is_alive()
    assert not bus.has_subscribers("a")
