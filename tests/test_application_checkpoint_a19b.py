from __future__ import annotations

import json
from pathlib import Path
from random import Random
from threading import Event, Lock

import pytest
import yaml
from test_application import FakeDisplay, RuntimeClock, Workspace, at
from test_demo import DemoClock, DemoWorkspace

import refrain.application as application
from refrain import ApplicationError, PersistentStateStore, PreparedImageArtifactStore
from refrain.checkpoint import CheckpointError, CheckpointStore
from refrain.display.coordinator import PublicationStatus


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    workspace = Workspace(tmp_path)
    config = yaml.safe_load(workspace.config.read_text(encoding="utf-8"))
    config["destinations"] = [
        {"id": "public", "type": "publish", "audience": "external", "aspect_ratio": "16:10", "resolution": [640, 400]},
        {"id": "private", "type": "publish", "audience": "internal", "aspect_ratio": "16:10", "resolution": [640, 400]},
    ]
    config["presentation"]["qr"] = {"external": "default-public", "internal": "default-private"}
    workspace.config.write_text(yaml.safe_dump(config), encoding="utf-8")
    workspace.entry(
        "ordinary",
        'source: "A Book"\nattribution: "An Author"\n'
        'qr:\n  - visibility: [external]\n    payload: "public"\n'
        '  - visibility: [internal]\n    payload: "private"\n'
        'quotations:\n  - "A quotation."\n',
    )
    return workspace


def _checkpoint(workspace: Workspace) -> dict:
    return json.loads(workspace.state.with_name("publication.json").read_text(encoding="utf-8"))


def test_initial_commit_resolves_qr_and_routes_distinct_audience_keys(workspace: Workspace) -> None:
    result, display = workspace.run(at(10, 7))
    checkpoint = _checkpoint(workspace)
    assert result.state.revision == 1
    assert checkpoint["content"]["qr"] == [
        {"visibility": ["external"], "payload": "public"},
        {"visibility": ["internal"], "payload": "private"},
    ]
    configuration = application.load_application_config(workspace.config)
    keys = application._destination_keys(configuration, checkpoint)
    assert keys["public"] != keys["private"]
    assert keys["public"].qr_payload == "public"
    assert keys["private"].qr_payload == "private"
    assert len(display.images) == 2
    for image in display.images:
        image.close()


@pytest.mark.parametrize("operation", ["checkpoint", "artifacts"])
def test_initial_invalidation_failure_prevents_state_commit(workspace, monkeypatch, operation) -> None:
    checkpoint = workspace.state.with_name("publication.json")
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("orphan", encoding="utf-8")

    def fail(_self):
        if operation == "checkpoint":
            raise CheckpointError("blocked")
        raise application.ArtifactStoreError("blocked")

    owner = CheckpointStore if operation == "checkpoint" else PreparedImageArtifactStore
    monkeypatch.setattr(owner, "invalidate" if operation == "checkpoint" else "invalidate_all", fail)
    with pytest.raises(ApplicationError, match="invalidate orphan"):
        workspace.run(at(10, 7))
    assert not workspace.state.exists()
    assert not workspace.history.exists()


@pytest.mark.parametrize("published", [False, True])
def test_failed_content_checkpoint_write_does_not_repeat_selection(workspace, monkeypatch, caplog, published) -> None:
    original = CheckpointStore.initialize

    def fail(self, state, qr):
        if published:
            original(self, state, qr)
        raise CheckpointError("disk full", published=published)

    monkeypatch.setattr(CheckpointStore, "initialize", fail)
    with pytest.raises(ApplicationError, match="content checkpoint"):
        workspace.run(at(10, 7))
    committed = workspace.load()
    assert committed is not None and committed.revision == 1
    assert len(workspace.history_records()) == 1
    monkeypatch.setattr(CheckpointStore, "initialize", original)
    monkeypatch.setattr(application, "_select_snapshot", lambda *_args: pytest.fail("must not reselect"))
    result, display = workspace.run(at(10, 7))
    assert result.state == committed
    qr = _checkpoint(workspace)["content"]["qr"]
    if published:
        assert [declaration["payload"] for declaration in qr] == ["public", "private"]
    else:
        assert qr == []
        assert "QR payloads cannot be recovered" in caplog.text
    assert len(workspace.history_records()) == 1
    for image in display.images:
        image.close()


def test_failed_reveal_checkpoint_update_recovers_state_first(workspace, monkeypatch) -> None:
    initial, display = workspace.run(at(10, 7))
    for image in display.images:
        image.close()
    before = _checkpoint(workspace)
    original = CheckpointStore.complete

    def fail_advanced(self, state, resolver):
        if state.highest_reveal_stage:
            raise CheckpointError("disk full")
        return original(self, state, resolver)

    monkeypatch.setattr(CheckpointStore, "complete", fail_advanced)
    with pytest.raises(ApplicationError, match="checkpoint"):
        workspace.run(at(10, 13))
    assert workspace.load().highest_reveal_stage == 1
    assert _checkpoint(workspace) == before
    monkeypatch.setattr(CheckpointStore, "complete", original)
    result, display = workspace.run(at(10, 13))
    recovered = _checkpoint(workspace)
    assert result.state.revision == initial.state.revision
    assert recovered["presentation"] == before["presentation"]
    assert recovered["content"]["qr"] == before["content"]["qr"]
    assert recovered["content"]["reveal_stage"]["source"] is True
    for image in display.images:
        image.close()


def test_refresh_rejects_checkpoint_changed_during_preparation(workspace, monkeypatch) -> None:
    _, display = workspace.run(at(10, 7))
    for image in display.images:
        image.close()
    config = application.load_application_config(workspace.config)
    original = application._recover_images

    def recover_then_corrupt(*args, **kwargs):
        artifacts = original(*args, **kwargs)
        workspace.state.with_name("publication.json").write_text("{", encoding="utf-8")
        return artifacts

    monkeypatch.setattr(application, "_recover_images", recover_then_corrupt)

    class Coordinator:
        desired_identity = (1, 0)

    def admit(*_args):
        pytest.fail("refresh must reject checkpoint changes during preparation")

    result = application._refresh_scheduled(
        Coordinator(),
        PersistentStateStore(workspace.state),
        PreparedImageArtifactStore(workspace.artifacts),
        config,
        Random(1),
        lambda: at(10, 7),
        Event(),
        Lock(),
        admit,
    )
    assert result.result.status is PublicationStatus.INVALID


def test_continuous_checkpoint_loss_replaces_same_stage_in_memory_artifacts(workspace, monkeypatch) -> None:
    records = []

    class Coordinator:
        def __init__(self, *_args, **_kwargs):
            self.desired_identity = None

        def publish_with_metadata(self, identity, images, metadata, *, destination_keys):
            records.append(
                (identity, dict(destination_keys), next(iter(metadata.values()))["checkpoint"]["content"]["qr"])
            )
            self.desired_identity = identity
            for image in images.values():
                image.close()

        def clear_desired(self):
            self.desired_identity = None

        def close(self):
            pass

    monkeypatch.setattr(application, "DisplayPublicationCoordinator", Coordinator)

    def corrupt():
        workspace.state.with_name("publication.json").write_text("{", encoding="utf-8")

    clock = RuntimeClock(at(10, 7), [corrupt])
    application.run_application(
        workspace.config,
        workspace.state,
        workspace.artifacts,
        history_path=workspace.history,
        shutdown_event=clock,
        random_source=Random(1),
        wall_clock=lambda: clock.now,
        monotonic_clock=lambda: clock.elapsed,
        scheduling_wait=clock.scheduling_wait,
        backend_factory=lambda _config: FakeDisplay(),
    )
    assert [record[0] for record in records] == [(1, 0), (1, 0)]
    assert records[0][2] and records[1][2] == []
    assert records[0][1] != records[1][1]
    assert workspace.load().revision == 1
    assert len(workspace.history_records()) == 1


def test_demo_post_commit_checkpoint_failure_starts_next_selection_at_stage_zero(tmp_path, monkeypatch) -> None:
    demo = DemoWorkspace(tmp_path, monkeypatch)
    demo.entry()
    demo.clock = DemoClock(waits=5)
    original = CheckpointStore.initialize
    coordinator_factory = application.DisplayPublicationCoordinator
    attempts = []

    def create_coordinator(*args, **kwargs):
        coordinator = coordinator_factory(*args, **kwargs)
        coordinator.clear_desired = lambda: setattr(coordinator, "desired_identity", None)
        return coordinator

    def fail_second_selection(self, state, qr):
        attempts.append(state.revision)
        if state.revision == 2:
            raise CheckpointError("disk full")
        return original(self, state, qr)

    monkeypatch.setattr(application, "DisplayPublicationCoordinator", create_coordinator)
    monkeypatch.setattr(CheckpointStore, "initialize", fail_second_selection)
    demo.run()
    assert [publication[0] for publication in demo.publications] == [(1, 0), (1, 1), (1, 2), (2, 0)]
    assert demo.publications[-1][2].highest_reveal_stage == 0
    assert attempts == [1, 2]
    assert len(demo.selected) == 2
    demo.assert_clean()
