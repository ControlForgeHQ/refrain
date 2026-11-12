from __future__ import annotations

import json
import os
import time
from multiprocessing.connection import Client
from pathlib import Path
from random import Random
from threading import Event, Lock, Thread, current_thread

import pytest
from PIL import Image
from test_application import Workspace, at, ordinary

import refrain.__main__ as cli
import refrain.application as application
import refrain.runtime_control as control_module
from refrain.display.coordinator import DisplayPublicationCoordinator
from refrain.ownership import InstallationOwnership, OwnershipError
from refrain.paths import resolve_application_paths
from refrain.runtime_control import RuntimeControlClient


def test_stale_staging_cleanup_requires_resident_ownership(tmp_path, monkeypatch):
    for name in (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
    ):
        monkeypatch.setenv(name, str(tmp_path / name))
    paths = resolve_application_paths()
    metadata = Path(paths.control_metadata_file)
    staging = metadata.with_name(metadata.name + ".transient")
    staging.mkdir(parents=True)
    if os.name != "nt":
        metadata.parent.chmod(0o700)
    (staging / "0.png").write_bytes(b"stale")
    ownership_path = Path(paths.ownership_file)
    called = []

    def run(_arguments, _paths, _ownership):
        called.append(True)
        assert staging.exists()
        with pytest.raises(OwnershipError):
            InstallationOwnership(ownership_path).acquire()
        coordinator = DisplayPublicationCoordinator(())
        server = control_module.RuntimeControlServer(coordinator, metadata, lambda _admit: None)
        try:
            server.start()
            assert not staging.exists()
            assert metadata.exists()
        finally:
            server.close()
            coordinator.close()
        return 0

    monkeypatch.setattr(cli, "_run_runtime", run)
    with InstallationOwnership(ownership_path):
        assert cli.main([]) == 1
        assert staging.exists()
        assert not called
    assert cli.main([]) == 0
    assert called == [True]


@pytest.fixture
def resident(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "_CONTROL_SHUTDOWN_TIMEOUT", 0.1)
    workspace = Workspace(tmp_path)
    ordinary(workspace)
    workspace.config.write_text(
        workspace.config.read_text().replace(
            '- type: "waveshare-13in3-e"',
            '- type: "image-server"\n'
            "      outputs:\n"
            '        - id: "one"\n'
            '          aspect_ratio: "16:9"\n'
            "          resolution: [800, 450]\n"
            '        - id: "two"\n'
            '          aspect_ratio: "16:9"\n'
            "          resolution: [800, 450]",
        )
    )
    shutdown = Event()
    published, pixels, closed, captured = [], [], Event(), []
    lock = Lock()
    slow_entered, release_slow = Event(), Event()
    scheduler_waiting = Event()
    clock = [at(10, 13)]
    hold_refresh = Event()
    errors = []
    deferred = []

    class Backend:
        def publish(self, destination, image):
            with lock:
                index = len(published)
            if index >= 2 and hold_refresh.is_set():
                slow_entered.set()
                assert release_slow.wait(10)
            pixel = image.getpixel((0, 0))
            with lock:
                published.append(destination.identifier)
                pixels.append(pixel)

        def close(self):
            closed.set()

    coordinator_factory = application.DisplayPublicationCoordinator

    class CapturingCoordinator(coordinator_factory):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(self)

    monkeypatch.setattr(application, "DisplayPublicationCoordinator", CapturingCoordinator)
    metadata = tmp_path / "control" / "endpoint.json"

    def wait_for_schedule(_deadline, event, **_kwargs):
        scheduler_waiting.set()
        return event.wait()

    def run():
        try:
            application.run_application(
                workspace.config,
                workspace.state,
                workspace.artifacts,
                history_path=workspace.history,
                shutdown_event=shutdown,
                random_source=Random(1),
                backend_factory=lambda _: Backend(),
                wall_clock=lambda: clock[0],
                scheduling_wait=wait_for_schedule,
                pending_shutdown=lambda threads, finish: deferred.append((threads, finish)),
                control_metadata_path=metadata,
            )
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if errors:
                raise errors[0]
            if captured and captured[0].desired_identity and metadata.exists():
                identity = captured[0].desired_identity
                acknowledgements = captured[0].acknowledgements
                if acknowledgements and all(value == identity for value in acknowledgements.values()):
                    break
            time.sleep(0.01)
        else:
            pytest.fail("resident runtime did not start and publish")
        assert scheduler_waiting.wait(5)
        yield (
            metadata,
            shutdown,
            published,
            closed,
            hold_refresh,
            slow_entered,
            release_slow,
            thread,
            deferred,
            errors,
            workspace,
            captured[0],
            clock,
            pixels,
        )
    finally:
        release_slow.set()
        shutdown.set()
        thread.join(10)
        for workers, finish in deferred:
            for worker in workers:
                worker.join(10)
            finish()
        assert not thread.is_alive()
        assert not errors


def _connection(path):
    metadata = json.loads(path.read_text())
    connection = Client(metadata["address"], family=metadata["family"])
    connection.send_bytes(json.dumps({"credential": metadata["credential"]}).encode())
    assert json.loads(connection.recv_bytes())["status"] == "authenticated"
    return connection


def test_real_resident_listener_and_refresh(resident):
    metadata, _, published, *_ = resident
    client = RuntimeControlClient(metadata)
    assert [item["identifier"] for item in client.discover()] == ["image-server:one", "image-server:two"]
    assert client.refresh().status.value == "succeeded"
    assert published == ["one", "two", "one", "two"]


def test_slow_refresh_preparation_does_not_block_scheduled_reveal(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path)
    ordinary(workspace)
    workspace.config.write_text(
        workspace.config.read_text().replace(
            '- type: "waveshare-13in3-e"',
            '- type: "window"\n      aspect_ratio: "16:9"\n      resolution: [800, 450]',
        )
    )
    shutdown, wake, preparing, release = Event(), Event(), Event(), Event()
    clock = [at(10, 11)]
    metadata = tmp_path / "control" / "endpoint.json"
    coordinators, results, errors = [], [], []
    factory = application.DisplayPublicationCoordinator
    recover = application._recover_images

    class Backend:
        def publish(self, destination, image):
            image.getpixel((0, 0))

        def close(self):
            pass

    class Coordinator(factory):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            coordinators.append(self)

    def slow_recover(*args, **kwargs):
        if current_thread().name == "refrain-control-request":
            preparing.set()
            assert release.wait(10)
        return recover(*args, **kwargs)

    def wait_for_schedule(_deadline, _event, **_kwargs):
        wake.wait(0.1)
        wake.clear()
        return shutdown.is_set()

    def run():
        try:
            application.run_application(
                workspace.config,
                workspace.state,
                workspace.artifacts,
                history_path=workspace.history,
                shutdown_event=shutdown,
                backend_factory=lambda _: Backend(),
                wall_clock=lambda: clock[0],
                scheduling_wait=wait_for_schedule,
                control_metadata_path=metadata,
            )
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(application, "DisplayPublicationCoordinator", Coordinator)
    monkeypatch.setattr(application, "_recover_images", slow_recover)
    thread = Thread(target=run, daemon=True)
    thread.start()
    client_thread = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if coordinators and coordinators[0].has_successful_publication((1, 0)) and metadata.exists():
                break
            time.sleep(0.01)
        else:
            pytest.fail(f"resident startup did not complete: {errors}")
        client_thread = Thread(target=lambda: results.append(RuntimeControlClient(metadata).refresh()), daemon=True)
        client_thread.start()
        assert preparing.wait(5)
        clock[0] = at(10, 13)
        wake.set()
        assert coordinators[0].wait_for_publication((1, 1), timeout=5)
        assert workspace.load().highest_reveal_stage == 1
        release.set()
        client_thread.join(5)
        assert not client_thread.is_alive()
        assert results[0].status.value == "invalid"
    finally:
        release.set()
        shutdown.set()
        wake.set()
        if client_thread is not None:
            client_thread.join(10)
        thread.join(10)
        assert not thread.is_alive()
        assert not errors


def test_real_transient_preserves_scheduled_state_and_acknowledgements(resident):
    metadata, _, published, _, _, _, _, _, _, _, workspace, coordinator, _, pixels = resident
    before_state = workspace.state.read_bytes()
    before_history = workspace.history.read_bytes()
    before_artifacts = {path: path.read_bytes() for path in workspace.artifacts.rglob("*") if path.is_file()}
    before_identity = coordinator.desired_identity
    before_acknowledgements = coordinator.acknowledgements
    client = RuntimeControlClient(metadata)
    records = client.discover()
    specs = {item["identifier"]: item["output_specification"] for item in records}
    specification = records[0]["output_specification"]
    with Image.new("RGB", specification.requested_output_size, (17, 81, 93)) as image:
        result = client.publish_transient("all", specs, {specification: image})
    assert result.status.value == "succeeded"
    assert published == ["one", "two", "one", "two"]
    assert pixels[-2:] == [(17, 81, 93), (17, 81, 93)]
    assert coordinator.desired_identity == before_identity
    assert coordinator.acknowledgements == before_acknowledgements
    assert workspace.state.read_bytes() == before_state
    assert workspace.history.read_bytes() == before_history
    assert {path: path.read_bytes() for path in workspace.artifacts.rglob("*") if path.is_file()} == before_artifacts


def test_newly_due_scheduled_stage_rejects_transient_before_publication(resident):
    metadata, _, published, _, _, _, _, _, _, _, workspace, coordinator, clock, _ = resident
    before_identity = coordinator.desired_identity
    before_acknowledgements = coordinator.acknowledgements
    before_state = workspace.state.read_bytes()
    client = RuntimeControlClient(metadata)
    records = client.discover()
    specs = {item["identifier"]: item["output_specification"] for item in records}
    specification = records[0]["output_specification"]
    # The scheduler remains asleep while the control request observes the newly due stage.
    clock[0] = at(10, 18)
    with Image.new("RGB", specification.requested_output_size, (17, 81, 93)) as image:
        result = client.publish_transient("all", specs, {specification: image})
    assert result.status.value == "busy"
    assert published == ["one", "two"]
    assert coordinator.desired_identity == before_identity
    assert coordinator.acknowledgements == before_acknowledgements
    assert workspace.state.read_bytes() == before_state


def test_disconnect_during_real_refresh_preparation_does_not_publish(resident, monkeypatch):
    metadata, _, published, *_ = resident
    entered, release, finished, guard_checked = Event(), Event(), Event(), Event()
    original_recover = application._recover_images
    original_refresh = application._refresh_scheduled
    original_check = control_module._ensure_connected
    checks = 0

    def slow_recover(*args, **kwargs):
        if current_thread().name == "refrain-control-request":
            entered.set()
            assert release.wait(5)
        return original_recover(*args, **kwargs)

    def observe_refresh(*args, **kwargs):
        try:
            return original_refresh(*args, **kwargs)
        finally:
            finished.set()

    def observe_check(connection):
        nonlocal checks
        checks += 1
        if checks == 2:
            guard_checked.set()
        return original_check(connection)

    monkeypatch.setattr(application, "_recover_images", slow_recover)
    monkeypatch.setattr(application, "_refresh_scheduled", observe_refresh)
    monkeypatch.setattr(control_module, "_ensure_connected", observe_check)
    connection = _connection(metadata)
    try:
        connection.send_bytes(b'{"version":1,"operation":"refresh"}')
        assert entered.wait(5)
        connection.close()
        release.set()
        assert finished.wait(5)
        assert guard_checked.is_set()
        assert published == ["one", "two"]
    finally:
        release.set()
        connection.close()


def test_real_shutdown_defers_coordinator_until_admitted_refresh_completes(resident):
    metadata, shutdown, published, closed, hold, entered, release, thread, deferred, errors, *_ = resident
    hold.set()
    connection = _connection(metadata)
    try:
        connection.send_bytes(b'{"version":1,"operation":"refresh"}')
        assert json.loads(connection.recv_bytes())["status"] == "accepted"
        assert entered.wait(5)
        connection.close()
        shutdown.set()
        thread.join(5)
        assert not thread.is_alive()
        assert not errors
        assert deferred and not closed.is_set()
        release.set()
        workers, _finish = deferred[0]
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive()
        assert published == ["one", "two", "one", "two"]
    finally:
        release.set()
        connection.close()


def test_shutdown_closes_backend_before_stuck_unadmitted_handler_exits(resident, monkeypatch):
    metadata, shutdown, published, closed, _, _, _, thread, deferred, errors, *_ = resident
    entered, release = Event(), Event()
    original_refresh = application._refresh_scheduled

    def blocked_refresh(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original_refresh(*args, **kwargs)

    monkeypatch.setattr(application, "_refresh_scheduled", blocked_refresh)
    connection = _connection(metadata)
    try:
        connection.send_bytes(b'{"version":1,"operation":"refresh"}')
        assert entered.wait(5)
        shutdown.set()
        thread.join(5)
        assert not thread.is_alive()
        assert not errors
        assert deferred
        assert closed.wait(5)
        assert published == ["one", "two"]
        release.set()
        for worker in deferred[0][0]:
            worker.join(5)
            assert not worker.is_alive()
        assert published == ["one", "two"]
    finally:
        release.set()
        connection.close()
