import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(ENGINE_DIR / "Script"))


def test_translation_round_robin_dispatches_one_chapter_per_branch():
    from Bot.daemons import _select_round_robin_tasks

    rows = [
        ("a", ["a1", "a2"]),
        ("b", ["b1", "b2"]),
        ("c", ["c1", "c2"]),
        ("d", ["d1", "d2"]),
        ("e", ["e1", "e2"]),
    ]

    tasks, cursor = _select_round_robin_tasks(rows, capacity=4, cursor=0)
    assert tasks == [("a", "a1"), ("b", "b1"), ("c", "c1"), ("d", "d1")]

    tasks2, _ = _select_round_robin_tasks(rows, capacity=4, cursor=cursor)
    assert tasks2 == [("e", "e1"), ("a", "a1"), ("b", "b1"), ("c", "c1")]


def test_translation_round_robin_skips_active_projects():
    from Bot.daemons import _select_round_robin_tasks

    rows = [("a", ["a1"]), ("b", ["b1"]), ("c", ["c1"])]
    tasks, _ = _select_round_robin_tasks(rows, active_projects={"b"}, capacity=4, cursor=0)

    assert tasks == [("a", "a1"), ("c", "c1")]


def test_crawl_queue_claims_only_one_running_job(tmp_path, monkeypatch):
    from Bot import crawl_queue

    monkeypatch.setattr(crawl_queue, "QUEUE_PATH", tmp_path / "crawl_queue.json")

    first, created_first = crawl_queue.enqueue_job(1, "First", "https://example.test/1", novel_id="first")
    second, created_second = crawl_queue.enqueue_job(1, "Second", "https://example.test/2", novel_id="second")

    assert created_first is True
    assert created_second is True
    assert crawl_queue.claim_next_job()["novel_id"] == first["novel_id"]
    assert crawl_queue.claim_next_job() is None

    crawl_queue.finish_job(first["job_id"], "done")
    assert crawl_queue.claim_next_job()["novel_id"] == second["novel_id"]
