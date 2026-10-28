import json
import threading

import pytest
from dbutil import db

from app.core.config import Settings
from app.core.db import Approvals, Database
from app.core.legacy_import import import_legacy_files
from app.stages import feedback, implementer, planner, reviewer, tester


def impl_of(version=1):
    store = implementer.ImplementationStore(db())
    run = store.create("AB-1", 1)
    run.branch, run.base_commit = "AB-1_x", "abc"
    return store.save(run)


def test_runs_are_versioned_and_latest_is_the_highest():
    store = planner.PlanStore(db())
    assert store.latest("AB-1") is None and store.versions("AB-1") == []
    first = store.create("AB-1", "Backlog", None)
    second = store.create("AB-1", "Backlog", "more")
    assert (first.version, second.version) == (1, 2)
    assert [p.version for p in store.versions("AB-1")] == [1, 2]
    assert store.latest("AB-1").feedback == "more"
    second.state = "ready"
    store.save(second)
    assert store.latest("AB-1").state == "ready"
    assert len(store.versions("AB-1")) == 2


def test_kinds_and_cards_are_separate():
    planner.PlanStore(db()).create("AB-1", "Backlog", None)
    planner.PlanStore(db()).create("AB-2", "Backlog", None)
    implementer.ImplementationStore(db()).create("AB-1", 1)
    assert planner.PlanStore(db()).card_keys() == ["AB-1", "AB-2"]
    assert implementer.ImplementationStore(db()).card_keys() == ["AB-1"]
    assert implementer.ImplementationStore(db()).latest("AB-2") is None


def test_data_survives_a_new_connection_and_invalid_keys_are_rejected(db_file):
    planner.PlanStore(db()).create("AB-1", "Backlog", None)
    fresh = Database(db_file)
    assert planner.PlanStore(fresh).latest("AB-1").version == 1
    with pytest.raises(ValueError):
        planner.PlanStore(db()).latest("../evil")


def test_concurrent_creates_get_distinct_versions():
    store = planner.PlanStore(db())
    errors = []

    def create():
        try:
            store.create("AB-1", "Backlog", None)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=create) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    versions = [p.version for p in store.versions("AB-1")]
    assert versions == sorted(set(versions))
    assert len(versions) + len(errors) == 4


def test_comments_keep_their_order_and_can_be_resolved():
    store = feedback.FeedbackStore(db())
    a = store.add("AB-1", feedback.CommentInput(text="one"))
    b = store.add("AB-1", feedback.CommentInput(text="two"))
    assert [c.text for c in store.comments("AB-1")] == ["one", "two"]
    store.resolve("AB-1", {a.id}, 1)
    assert [c.status for c in store.comments("AB-1")] == ["resolved", "pending"]
    assert store.delete("AB-1", b.id) and not store.delete("AB-1", b.id)
    assert store.comments("AB-2") == []


def test_test_configs_roundtrip():
    configs = tester.ConfigStore(db())
    app = tester.AppSpec(
        name="api",
        start_command="run",
        workdir=".",
        ready_url="http://localhost:6000",
    )
    assert configs.load("AB") is None and configs.projects() == []
    configs.save("AB", [app], "AB-1")
    configs.save("AB", [app, app.model_copy(update={"name": "web"})], "AB-2")
    assert [a.name for a in configs.load("AB").apps] == ["api", "web"]
    assert configs.projects() == ["AB"]
    assert configs.delete("AB") and not configs.delete("AB")
    with pytest.raises(ValueError):
        configs.load("../x")


def write_legacy(settings, tmp_path):
    """Lay out JSON files the way the pre-SQLite version did."""
    src = Database(tmp_path / "src.db")
    plan = planner.PlanStore(src).create("AB-1", "Backlog", None)
    impl = implementer.ImplementationStore(src).create("AB-1", 1)
    impl.branch, impl.base_commit = "AB-1_x", "abc"
    review = reviewer.ReviewStore(src).create("AB-1", impl)
    run = tester.TestStore(src, tmp_path).create("AB-1", impl, 1)
    fb = feedback.FeedbackStore(src)
    frun = fb.create("AB-1", impl)
    comment = fb.add("AB-1", feedback.CommentInput(text="note"))

    def put(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    put(settings.plans_dir / "AB-1" / "1.json", plan.model_dump_json())
    put(settings.implementations_dir / "AB-1" / "1.json", impl.model_dump_json())
    put(settings.reviews_dir / "AB-1" / "1.json", review.model_dump_json())
    put(settings.test_runs_dir / "AB-1" / "1.json", run.model_dump_json())
    put(settings.test_runs_dir / "AB-1" / "1-app1.log", "log")
    put(settings.feedback_dir / "AB-1" / "runs" / "1.json", frun.model_dump_json())
    put(
        settings.feedback_dir / "AB-1" / "comments.json",
        json.dumps([comment.model_dump()]),
    )
    cfg = tester.SavedConfig(
        project="AB",
        apps=[
            tester.AppSpec(
                name="api",
                start_command="run",
                workdir=".",
                ready_url="http://localhost:6000",
            )
        ],
        saved_from="AB-1",
        saved_at="now",
    )
    put(settings.test_configs_dir / "AB.json", cfg.model_dump_json())
    # junk that must be skipped
    put(settings.plans_dir / "AB-2" / "1.json", "{not json")
    put(settings.plans_dir / "notes" / "1.json", plan.model_dump_json())
    put(settings.plans_dir / "AB-9" / "1.json", plan.model_dump_json())  # wrong card


def test_legacy_json_files_are_imported_once(tmp_path):
    settings = Settings(
        plans_dir=tmp_path / "plans",
        implementations_dir=tmp_path / "impls",
        reviews_dir=tmp_path / "reviews",
        test_runs_dir=tmp_path / "runs",
        feedback_dir=tmp_path / "fb",
        test_configs_dir=tmp_path / "cfg",
    )
    write_legacy(settings, tmp_path)
    counts = import_legacy_files(settings)
    assert counts == {
        "plan": 1,
        "implementation": 1,
        "review": 1,
        "test": 1,
        "feedback": 1,
        "comments": 1,
        "test_configs": 1,
    }
    assert planner.PlanStore(db()).card_keys() == ["AB-1"]
    assert implementer.ImplementationStore(db()).latest("AB-1").branch == "AB-1_x"
    assert reviewer.ReviewStore(db()).latest("AB-1").version == 1
    assert tester.TestStore(db(), tmp_path).latest("AB-1").state == "preparing"
    assert feedback.FeedbackStore(db()).latest("AB-1").version == 1
    assert feedback.FeedbackStore(db()).comments("AB-1")[0].text == "note"
    assert tester.ConfigStore(db()).load("AB").saved_from == "AB-1"

    # a second start must not bring deleted data back or duplicate anything
    tester.ConfigStore(db()).delete("AB")
    assert import_legacy_files(settings) == {}
    assert tester.ConfigStore(db()).load("AB") is None
    assert len(planner.PlanStore(db()).versions("AB-1")) == 1


def test_import_with_no_legacy_folders_is_harmless(tmp_path):
    settings = Settings(
        plans_dir=tmp_path / "x1",
        implementations_dir=tmp_path / "x2",
        reviews_dir=tmp_path / "x3",
        test_runs_dir=tmp_path / "x4",
        feedback_dir=tmp_path / "x5",
        test_configs_dir=tmp_path / "x6",
    )
    assert set(import_legacy_files(settings).values()) == {0}


def test_approval_is_withdrawn_when_the_branch_changes(tmp_path):
    approvals = Approvals(db())
    impl = impl_of()
    reviews = reviewer.ReviewStore(db())
    review = reviews.create("AB-1", impl)
    review.state = "clean"
    reviews.save(review)
    tester.TestStore(db(), tmp_path).create("AB-1", impl, 1)

    def approved():
        approvals.approve("AB-1")
        return approvals.get("AB-1") is not None

    # nothing that leaves the code alone withdraws it
    assert approved()
    reviews.save(review)
    tester.TestStore(db(), tmp_path).create("AB-1", impl, 1)
    assert approvals.keys() == ["AB-1"]

    review.state = "fixed"  # auto-review fix commits
    reviews.save(review)
    assert approvals.get("AB-1") is None

    approved()
    reviews.create("AB-1", impl)  # a new review run
    assert approvals.get("AB-1") is None

    approved()
    implementer.ImplementationStore(db()).create("AB-1", 1)  # re-implementation
    assert approvals.get("AB-1") is None

    approved()
    fb = feedback.FeedbackStore(db())
    run = fb.create("AB-1", impl)  # manual review feedback starts
    assert approvals.get("AB-1") is None
    approved()
    run.state = "failed"
    fb.save(run)
    assert approvals.get("AB-1") is not None  # a failed run changed nothing we know of
    run.state = "done"
    fb.save(run)
    assert approvals.get("AB-1") is None


def test_approvals_are_per_card():
    approvals = Approvals(db())
    approvals.approve("AB-1")
    approvals.approve("AB-2")
    assert approvals.clear("AB-1") and not approvals.clear("AB-1")
    assert approvals.keys() == ["AB-2"]
    with pytest.raises(ValueError):
        approvals.get("../x")
