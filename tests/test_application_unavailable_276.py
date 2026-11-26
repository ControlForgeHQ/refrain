from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from test_application import RuntimeClock, Workspace, at, ordinary, run_continuously
from test_persistence import _write_document

import refrain.application as application
import refrain.display.coordinator as coordinator_module
import refrain.preparation as preparation
from refrain.display import DisplayBackendInitializationError, DisplayBackendUpdateError


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


def test_uninitialized_unavailable_is_fatal(workspace: Workspace) -> None:
    shutil.rmtree(workspace.content)
    with pytest.raises(application.ApplicationError, match="initial presentation"):
        workspace.run(at(10, 8))
    assert not workspace.state.exists()


def test_invalid_selection_replaced_using_recovered_revision_and_history(workspace: Workspace) -> None:
    ordinary(workspace)
    original, _ = workspace.run(at(10, 8))
    document = json.loads(workspace.state.read_bytes())
    document["state"]["highest_reveal_stage"] = True
    _write_document(workspace.state, document)

    replacement, _ = workspace.run(at(10, 8))

    assert replacement.state.revision == original.state.revision + 1
    assert replacement.state.repetition_history == original.state.repetition_history
    assert len(workspace.history_records()) == 2


def test_invalid_selection_and_unavailable_library_preserve_state(workspace: Workspace) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    document = json.loads(workspace.state.read_bytes())
    document["state"]["highest_reveal_stage"] = True
    _write_document(workspace.state, document)
    original = workspace.state.read_bytes()
    shutil.rmtree(workspace.content)

    result, display = workspace.run(at(10, 8))

    assert result.state is None and result.presented_stage is None
    assert workspace.state.read_bytes() == original
    assert not display.images


def test_resident_library_retry_is_monotonic_and_not_bypassed_by_wakes(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    original = workspace.state.read_bytes()
    shutil.rmtree(workspace.content)
    clock = RuntimeClock(at(11, 8))
    attempts = []
    select = application._select_snapshot

    def select_recording(*args, **kwargs):
        attempts.append(clock.elapsed)
        return select(*args, **kwargs)

    monkeypatch.setattr(application, "_select_snapshot", select_recording)
    wakes = iter((100, 199, 1))

    def wait(deadline, shutdown, **kwargs):
        elapsed = next(wakes, None)
        if elapsed is None:
            shutdown.set()
        else:
            assert workspace.state.read_bytes() == original
            clock.elapsed += elapsed
            clock.now += timedelta(seconds=elapsed)
            if clock.elapsed == 300:
                workspace.content.mkdir()
                ordinary(workspace)
        return shutdown.is_set()

    run_continuously(workspace, clock, monkeypatch, scheduling_wait=wait)

    assert attempts == [0, 300]
    assert workspace.load().revision == 2


def test_startup_fallback_rechecks_date_after_rendering(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("special", 'eligibility:\n  - month: 3\n    day: 11\nquotations:\n  - "Tomorrow"\n')
    times = iter((at(10, 8), at(11, 8), at(11, 8), at(11, 8), at(11, 8), at(11, 8)))
    images = []

    def prepare(configuration, keys, **kwargs):
        result = {
            key: (Image.new("RGB", getattr(key, "output_specification", key).requested_output_size),) for key in keys
        }
        images.extend(variant[0] for variant in result.values())
        return result

    monkeypatch.setattr(application, "prepare_no_eligible_fallback", prepare)
    result, display = workspace.run(at(10, 8), wall_clock=lambda: next(times, at(11, 8)))

    assert result.state.snapshot.display_date.day == 11
    assert len(display.images) == 1
    with pytest.raises(ValueError, match="closed"):
        images[0].getpixel((0, 0))


def test_unavailable_retry_immediately_restarts_on_different_date(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    shutil.rmtree(workspace.content)
    clock = RuntimeClock(at(11, 8))
    attempts = []
    select = application._select_snapshot

    def select_recording(*args, **kwargs):
        attempts.append((clock.now, clock.elapsed))
        return select(*args, **kwargs)

    monkeypatch.setattr(application, "_select_snapshot", select_recording)

    def wait(deadline, shutdown, **kwargs):
        if not attempts or len(attempts) == 1:
            clock.now = at(12, 8)
            clock.elapsed = 1
            workspace.content.mkdir()
            ordinary(workspace)
        else:
            shutdown.set()
        return shutdown.is_set()

    run_continuously(workspace, clock, monkeypatch, scheduling_wait=wait)

    assert [elapsed for _, elapsed in attempts] == [0, 1]
    assert workspace.load().snapshot.display_date.day == 12


def test_fallback_does_not_repeat_selection_until_next_date(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("special", 'eligibility:\n  - month: 3\n    day: 11\nquotations:\n  - "Tomorrow"\n')
    clock = RuntimeClock(at(10, 8))
    attempts = []
    select = application._select_snapshot

    def select_recording(*args, **kwargs):
        attempts.append(args[1])
        return select(*args, **kwargs)

    def prepare(configuration, keys, **kwargs):
        return {
            key: (Image.new("RGB", getattr(key, "output_specification", key).requested_output_size),) for key in keys
        }

    monkeypatch.setattr(application, "_select_snapshot", select_recording)
    monkeypatch.setattr(application, "prepare_no_eligible_fallback", prepare)
    wakes = iter((at(10, 9), at(11, 8)))

    def wait(deadline, shutdown, **kwargs):
        when = next(wakes, None)
        if when is None:
            shutdown.set()
        else:
            clock.move(when)
        return shutdown.is_set()

    presentations, _, _ = run_continuously(workspace, clock, monkeypatch, scheduling_wait=wait)

    assert [day.day for day in attempts] == [10, 11]
    assert presentations.count((-1, attempts[0].toordinal())) == 1
    assert workspace.load().snapshot.display_date.day == 11
    assert len(workspace.history_records()) == 1


def test_fallback_then_unavailable_library_remains_resident_and_recovers(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("special", 'eligibility:\n  - month: 4\nquotations:\n  - "Later"\n')
    clock = RuntimeClock(at(10, 8))
    attempts = []
    select = application._select_snapshot

    def select_recording(*args, **kwargs):
        attempts.append((args[1], clock.elapsed))
        return select(*args, **kwargs)

    def fallback(configuration, keys, **kwargs):
        return {
            key: (Image.new("RGB", getattr(key, "output_specification", key).requested_output_size),) for key in keys
        }

    monkeypatch.setattr(application, "_select_snapshot", select_recording)
    monkeypatch.setattr(application, "prepare_no_eligible_fallback", fallback)
    wakes = 0

    def wait(deadline, shutdown, **kwargs):
        nonlocal wakes
        wakes += 1
        if wakes == 1:
            shutil.rmtree(workspace.content)
            clock.now = at(11, 8)
            clock.elapsed = 1
        elif wakes == 2:
            clock.now += timedelta(seconds=300)
            clock.elapsed += 300
            workspace.content.mkdir()
            ordinary(workspace)
        else:
            shutdown.set()
        return shutdown.is_set()

    presentations, _, _ = run_continuously(workspace, clock, monkeypatch, scheduling_wait=wait)

    assert [elapsed for _, elapsed in attempts] == [0, 1, 301]
    assert presentations == [(-1, at(10, 8).date().toordinal()), (1, 0)]
    assert workspace.load().snapshot.display_date.day == 11


def test_invalid_selection_healthy_fallback_preserves_file(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    document = json.loads(workspace.state.read_bytes())
    document["state"]["highest_reveal_stage"] = True
    _write_document(workspace.state, document)
    original = workspace.state.read_bytes()
    (workspace.content / "ordinary.yaml").unlink()
    workspace.entry("special", 'eligibility:\n  - month: 4\nquotations:\n  - "Later"\n')

    def prepare(configuration, keys, **kwargs):
        return {
            key: (Image.new("RGB", getattr(key, "output_specification", key).requested_output_size),) for key in keys
        }

    monkeypatch.setattr(application, "prepare_no_eligible_fallback", prepare)
    result, display = workspace.run(at(10, 8))

    assert result.state is None and not result.selected_initial_quotation
    assert workspace.state.read_bytes() == original
    assert len(workspace.history_records()) == 1
    assert len(display.images) == 1


def test_fallback_still_presents_startup_information_view(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("special", 'eligibility:\n  - month: 4\nquotations:\n  - "Later"\n')
    workspace.config.write_text(workspace.config.read_text().replace("duration: 0", "duration: 60"))
    clock = RuntimeClock(at(10, 8))

    def information(configuration, specifications):
        return {key: (Image.new("RGB", key.requested_output_size),) for key in specifications}

    def fallback(configuration, keys, **kwargs):
        return {
            key: (Image.new("RGB", getattr(key, "output_specification", key).requested_output_size),) for key in keys
        }

    monkeypatch.setattr(application, "prepare_information_view", information)
    monkeypatch.setattr(application, "prepare_no_eligible_fallback", fallback)
    waits = 0

    def wait(deadline, wake_event, **kwargs):
        nonlocal waits
        waits += 1
        if waits == 1:
            clock.elapsed += 61
            clock.now += timedelta(seconds=61)
        else:
            clock.set()
        return wake_event.is_set()

    presentations, _, _ = run_continuously(
        workspace, clock, monkeypatch, scheduling_wait=wait, await_publication_before_scheduling=True
    )

    assert presentations == [application._INFORMATION_VIEW_IDENTITY, (-1, at(10, 8).date().toordinal())]
    assert not workspace.state.exists()


def test_unavailable_library_still_presents_information_without_shortening_retry(workspace: Workspace, monkeypatch):
    ordinary(workspace)
    workspace.run(at(10, 8))
    shutil.rmtree(workspace.content)
    workspace.config.write_text(workspace.config.read_text().replace("duration: 0", "duration: 60"))
    clock = RuntimeClock(at(11, 8))
    attempts = []
    select = application._select_snapshot

    def select_recording(*args, **kwargs):
        attempts.append(clock.elapsed)
        return select(*args, **kwargs)

    def information(configuration, specifications):
        return {key: (Image.new("RGB", key.requested_output_size),) for key in specifications}

    monkeypatch.setattr(application, "_select_snapshot", select_recording)
    monkeypatch.setattr(application, "prepare_information_view", information)
    wakes = iter((61, 239))

    def wait(deadline, wake_event, **kwargs):
        elapsed = next(wakes, None)
        if elapsed is None:
            clock.set()
        else:
            clock.elapsed += elapsed
            clock.now += timedelta(seconds=elapsed)
            if clock.elapsed == 300:
                workspace.content.mkdir()
                ordinary(workspace)
        return wake_event.is_set()

    presentations, _, _ = run_continuously(
        workspace, clock, monkeypatch, scheduling_wait=wait, await_publication_before_scheduling=True
    )

    assert attempts == [0, 300]
    assert presentations == [application._INFORMATION_VIEW_IDENTITY, (2, 0)]


def test_resident_discards_fallback_when_date_changes_during_rendering(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("special", 'eligibility:\n  - month: 3\n    day: 11\nquotations:\n  - "Tomorrow"\n')
    clock = RuntimeClock(at(10, 8))

    def fallback(configuration, keys, **kwargs):
        images = {
            key: (Image.new("RGB", getattr(key, "output_specification", key).requested_output_size),) for key in keys
        }
        clock.move(at(11, 8))
        return images

    monkeypatch.setattr(application, "prepare_no_eligible_fallback", fallback)
    presentations, _, _ = run_continuously(workspace, clock, monkeypatch)

    assert all(identity[0] != -1 for identity in presentations)
    assert workspace.load().snapshot.display_date.day == 11


def test_fallback_render_failure_retries_without_reselecting(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("special", 'eligibility:\n  - month: 4\nquotations:\n  - "Later"\n')
    clock = RuntimeClock(at(10, 8), retries=(lambda: None,))
    attempts = 0
    selections = 0
    select = application._select_snapshot

    def select_recording(*args, **kwargs):
        nonlocal selections
        selections += 1
        return select(*args, **kwargs)

    def fallback(configuration, keys, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise application.DailyImagePreparationError("render unavailable")
        return {
            key: (Image.new("RGB", getattr(key, "output_specification", key).requested_output_size),) for key in keys
        }

    monkeypatch.setattr(application, "_select_snapshot", select_recording)
    monkeypatch.setattr(application, "prepare_no_eligible_fallback", fallback)
    presentations, _, _ = run_continuously(workspace, clock, monkeypatch)

    assert selections == 1 and attempts == 2
    assert presentations == [(-1, at(10, 8).date().toordinal())]
    assert not workspace.state.exists()


def test_fallback_isolates_failed_variant_and_retries_only_that_variant(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("special", 'eligibility:\n  - month: 4\nquotations:\n  - "Later"\n')
    workspace.config.write_text(
        workspace.config.read_text().replace(
            '  - id: epaper\n    type: "waveshare-13in3-e"\n    audience: "internal"',
            '  - id: healthy\n    type: publish\n    audience: internal\n    aspect_ratio: "16:10"\n'
            "    resolution: [800, 500]\n"
            '  - id: recovering\n    type: publish\n    audience: internal\n    aspect_ratio: "4:3"\n'
            "    resolution: [800, 600]",
        )
    )
    clock = RuntimeClock(at(10, 8))
    canonical_calls = []
    render_calls = []
    received = []
    canonical = preparation.resolve_canonical_presentation
    render = preparation._prepare_daily_images_for_specification

    def resolve(*args, **kwargs):
        canonical_calls.append(1)
        return canonical(*args, **kwargs)

    def render_variant(snapshot, stages, config, specification, *args, **kwargs):
        render_calls.append(specification.requested_output_size)
        if specification.requested_output_size == (800, 600) and render_calls.count((800, 600)) == 1:
            raise preparation.DailyImagePreparationError("variant temporarily unavailable")
        return render(snapshot, stages, config, specification, *args, **kwargs)

    class Backend:
        def publish(self, destination, image):
            received.append(destination.identifier)

        def close(self):
            pass

    monkeypatch.setattr(preparation, "resolve_canonical_presentation", resolve)
    monkeypatch.setattr(preparation, "_prepare_daily_images_for_specification", render_variant)
    waits = 0

    def wait(deadline, shutdown, **kwargs):
        nonlocal waits
        waits += 1
        if waits == 1:
            clock.elapsed += 1
            clock.now += timedelta(seconds=1)
        else:
            shutdown.set()
        return shutdown.is_set()

    run_continuously(
        workspace,
        clock,
        monkeypatch,
        backend_factory=lambda _: Backend(),
        scheduling_wait=wait,
        await_publication_before_scheduling=True,
    )

    assert canonical_calls == [1]
    assert render_calls.count((800, 500)) == 1
    assert render_calls.count((800, 600)) == 2
    assert received == ["healthy", "recovering"]
    assert not workspace.state.exists() and not workspace.history.exists()


def test_startup_publishes_healthy_fallback_variant_when_another_fails(workspace: Workspace, monkeypatch) -> None:
    workspace.entry("special", 'eligibility:\n  - month: 4\nquotations:\n  - "Later"\n')
    workspace.config.write_text(
        workspace.config.read_text().replace(
            '  - id: epaper\n    type: "waveshare-13in3-e"\n    audience: "internal"',
            '  - id: healthy\n    type: publish\n    audience: internal\n    aspect_ratio: "16:10"\n'
            "    resolution: [800, 500]\n"
            '  - id: broken\n    type: publish\n    audience: internal\n    aspect_ratio: "4:3"\n'
            "    resolution: [800, 600]",
        )
    )
    render = preparation._prepare_daily_images_for_specification

    def render_variant(snapshot, stages, config, specification, *args, **kwargs):
        if specification.requested_output_size == (800, 600):
            raise preparation.DailyImagePreparationError("variant unavailable")
        return render(snapshot, stages, config, specification, *args, **kwargs)

    monkeypatch.setattr(preparation, "_prepare_daily_images_for_specification", render_variant)
    result, display = workspace.run(at(10, 8))

    assert result.presented_stage is None and not result.selected_initial_quotation
    assert display.sizes == [(800, 500)]
    assert not workspace.state.exists() and not workspace.history.exists()


def test_missing_fallback_variant_does_not_block_external_transient(workspace: Workspace) -> None:
    workspace.config.write_text(
        workspace.config.read_text().replace(
            '  - id: epaper\n    type: "waveshare-13in3-e"\n    audience: "internal"',
            '  - id: healthy\n    type: publish\n    audience: internal\n    aspect_ratio: "16:10"\n'
            "    resolution: [800, 500]\n"
            '  - id: broken\n    type: publish\n    audience: internal\n    aspect_ratio: "4:3"\n'
            "    resolution: [800, 600]",
        )
    )
    configuration = application.load_application_config(workspace.config)
    outputs = configuration.display_backends[0].outputs

    class Backend:
        def publish(self, destination, image):
            pass

        def close(self):
            pass

    coordinator = application.DisplayPublicationCoordinator(configuration.display_backends, lambda _: Backend())
    try:
        identity = (-1, at(10, 8).date().toordinal())
        healthy, broken = outputs
        coordinator.publish_transient_presentation(
            identity, {healthy.prepared_image_key: Image.new("RGB", (800, 500))}, allow_missing=True
        )
        assert coordinator.wait_for_publication(identity, timeout=2)
        assert coordinator.publication_results(identity)["broken"][1] is not None
        result = coordinator.publish_transient(
            "broken",
            {"broken": broken.output_specification},
            {broken.output_specification: Image.new("RGB", (800, 600))},
        ).wait(2)
        assert result.status is application.PublicationStatus.SUCCEEDED
    finally:
        coordinator.close()


def test_partial_fallback_retry_does_not_revive_unavailable_destination(workspace: Workspace, monkeypatch) -> None:
    workspace.config.write_text(
        workspace.config.read_text().replace(
            '  - id: epaper\n    type: "waveshare-13in3-e"\n    audience: "internal"',
            '  - id: unavailable\n    type: publish\n    audience: internal\n    aspect_ratio: "16:10"\n'
            "    resolution: [800, 500]\n"
            '  - id: recovering\n    type: publish\n    audience: internal\n    aspect_ratio: "4:3"\n'
            "    resolution: [800, 600]",
        )
    )
    configuration = application.load_application_config(workspace.config)
    unavailable, recovering = configuration.display_backends[0].outputs
    initializations = 0

    class Backend:
        def publish(self, destination, image):
            pass

        def close(self):
            pass

    def factory(_configuration):
        nonlocal initializations
        initializations += 1
        if initializations == 1:
            raise DisplayBackendInitializationError("initialization failed", recoverable=True)
        return Backend()

    monkeypatch.setattr(coordinator_module, "_MAX_RETRY_ATTEMPTS", 1)
    coordinator = application.DisplayPublicationCoordinator(configuration.display_backends, factory)
    try:
        identity = (-1, at(10, 8).date().toordinal())
        coordinator.publish_transient_presentation(
            identity, {unavailable.prepared_image_key: Image.new("RGB", (800, 500))}, allow_missing=True
        )
        assert not coordinator.wait_for_publication(identity, timeout=2)
        assert coordinator._states["unavailable"].terminal
        assert coordinator._states["unavailable"].pending is None

        coordinator.publish_transient_presentation(
            identity, {recovering.prepared_image_key: Image.new("RGB", (800, 600))}, allow_missing=True
        )
        assert coordinator.wait_for_publication(identity, timeout=2)
        assert coordinator._states["unavailable"].terminal
        assert coordinator._states["unavailable"].pending is None
        result = coordinator.publish_transient(
            "recovering",
            {"recovering": recovering.output_specification},
            {recovering.output_specification: Image.new("RGB", (800, 600))},
        ).wait(2)
        assert result.status is application.PublicationStatus.SUCCEEDED
    finally:
        coordinator.close()


def test_terminal_destination_missing_from_fallback_can_later_recover(workspace: Workspace, monkeypatch) -> None:
    workspace.config.write_text(
        workspace.config.read_text().replace(
            '  - id: epaper\n    type: "waveshare-13in3-e"\n    audience: "internal"',
            '  - id: first\n    type: publish\n    audience: internal\n    aspect_ratio: "16:10"\n'
            "    resolution: [800, 500]\n"
            '  - id: second\n    type: publish\n    audience: internal\n    aspect_ratio: "4:3"\n'
            "    resolution: [800, 600]",
        )
    )
    configuration = application.load_application_config(workspace.config)
    first, second = configuration.display_backends[0].outputs
    initializations = 0
    received = []

    class Backend:
        def publish(self, destination, image):
            received.append(destination.identifier)

        def close(self):
            pass

    def factory(_configuration):
        nonlocal initializations
        initializations += 1
        if initializations == 1:
            raise DisplayBackendInitializationError("initialization failed", recoverable=True)
        return Backend()

    monkeypatch.setattr(coordinator_module, "_MAX_RETRY_ATTEMPTS", 1)
    coordinator = application.DisplayPublicationCoordinator(configuration.display_backends, factory)
    try:
        coordinator.publish_transient_presentation(
            (-1, 1), {first.prepared_image_key: Image.new("RGB", (800, 500))}, allow_missing=True
        )
        assert not coordinator.wait_for_publication((-1, 1), timeout=2)
        assert coordinator._states["second"].terminal
        coordinator.clear_desired()
        coordinator.publish_transient_presentation(
            (-1, 2), {first.prepared_image_key: Image.new("RGB", (800, 500))}, allow_missing=True
        )
        assert coordinator.wait_for_publication((-1, 2), timeout=2)
        assert coordinator._states["second"].preparation_error is not None
        coordinator.publish_transient_presentation(
            (-1, 2), {second.prepared_image_key: Image.new("RGB", (800, 600))}, allow_missing=True
        )
        assert coordinator.wait_for_publication((-1, 2), timeout=2)
        assert received == ["first", "second"]
    finally:
        coordinator.close()


@pytest.mark.parametrize("failure", ["initialization", "publication"])
def test_transient_recovery_after_lost_fallback_does_not_block_shared_backend(workspace, monkeypatch, failure):
    workspace.config.write_text(
        workspace.config.read_text().replace(
            '  - id: epaper\n    type: "waveshare-13in3-e"\n    audience: "internal"',
            '  - id: first\n    type: publish\n    audience: internal\n    aspect_ratio: "16:10"\n'
            "    resolution: [800, 500]\n"
            '  - id: second\n    type: publish\n    audience: internal\n    aspect_ratio: "4:3"\n'
            "    resolution: [800, 600]",
        )
    )
    configuration = application.load_application_config(workspace.config)
    first, second = configuration.display_backends[0].outputs
    initializations = 0
    failed_publications = 0

    class Backend:
        def publish(self, destination, image):
            nonlocal failed_publications
            if failure == "publication" and destination.identifier == "first" and not failed_publications:
                failed_publications += 1
                raise DisplayBackendUpdateError("publication failed", recoverable=True)

        def close(self):
            pass

    def factory(_configuration):
        nonlocal initializations
        initializations += 1
        if failure == "initialization" and initializations == 1:
            raise DisplayBackendInitializationError("initialization failed", recoverable=True)
        return Backend()

    monkeypatch.setattr(coordinator_module, "_MAX_RETRY_ATTEMPTS", 1)
    coordinator = application.DisplayPublicationCoordinator(configuration.display_backends, factory)
    try:
        identity = (-1, at(10, 8).date().toordinal())
        coordinator.publish_transient_presentation(
            identity,
            {
                first.prepared_image_key: Image.new("RGB", (800, 500)),
                second.prepared_image_key: Image.new("RGB", (800, 600)),
            },
            allow_missing=True,
        )
        coordinator.wait_for_publication(identity, timeout=2)
        assert coordinator._states["first"].terminal
        assert coordinator._states["first"].pending is None
        assert coordinator._states["first"].preparation_error is not None
        for output in (first, second):
            result = coordinator.publish_transient(
                output.identifier,
                {output.identifier: output.output_specification},
                {output.output_specification: Image.new("RGB", output.output_specification.requested_output_size)},
            ).wait(2)
            assert result.status is application.PublicationStatus.SUCCEEDED
        assert coordinator._states["first"].preparation_error is not None
    finally:
        coordinator.close()


def test_older_terminal_failure_marks_queued_fallback_lost(workspace: Workspace, monkeypatch) -> None:
    configuration = application.load_application_config(workspace.config)
    output = configuration.display_backends[0].outputs[0]
    started = Event()
    release = Event()
    calls = 0

    class Backend:
        def publish(self, destination, image):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                assert release.wait(2)
                raise DisplayBackendUpdateError("older presentation failed", recoverable=True)

        def close(self):
            pass

    monkeypatch.setattr(coordinator_module, "_MAX_RETRY_ATTEMPTS", 1)
    coordinator = application.DisplayPublicationCoordinator(configuration.display_backends, lambda _: Backend())
    try:
        specification = output.output_specification
        image_size = specification.requested_output_size
        coordinator.publish_transient_presentation((0, -1), {output.prepared_image_key: Image.new("RGB", image_size)})
        assert started.wait(2)
        coordinator.publish_transient_presentation(
            (-1, 1), {output.prepared_image_key: Image.new("RGB", image_size)}, allow_missing=True
        )
        release.set()
        assert not coordinator.wait_for_publication((-1, 1), timeout=2)
        assert coordinator._states[output.identifier].preparation_error is not None
        for _ in range(2):
            result = coordinator.publish_transient(
                output.identifier,
                {output.identifier: specification},
                {specification: Image.new("RGB", image_size)},
            ).wait(2)
            assert result.status is application.PublicationStatus.SUCCEEDED
    finally:
        release.set()
        coordinator.close()


def test_invalid_reveal_request_warns_preserves_state_and_continues(workspace: Workspace, monkeypatch, caplog) -> None:
    ordinary(workspace)
    workspace.run(at(10, 8))
    state_before = workspace.state.read_bytes()
    checkpoint = workspace.state.with_name("publication.json")
    checkpoint_before = checkpoint.read_bytes()
    clock = RuntimeClock(at(10, 13))

    def reject_progress(store, revision, stage):
        raise ValueError(f"stage {stage} is invalid")

    monkeypatch.setattr(application.PersistentStateStore, "advance_reveal_progress", reject_progress)
    presentations, _, _ = run_continuously(workspace, clock, monkeypatch)

    assert presentations == [(1, 0)]
    assert workspace.state.read_bytes() == state_before
    assert checkpoint.read_bytes() == checkpoint_before
    assert "Invalid requested reveal stage" in caplog.text


def test_post_commit_checkpoint_failure_does_not_repeat_selection(workspace: Workspace, monkeypatch) -> None:
    ordinary(workspace)
    original = application.CheckpointStore.initialize
    calls = 0

    def fail_once(store, state, qr):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise application.CheckpointError("injected post-commit failure")
        return original(store, state, qr)

    monkeypatch.setattr(application.CheckpointStore, "initialize", fail_once)
    result, _ = workspace.run(at(10, 8))

    assert result.state.revision == 1
    assert workspace.load().revision == 1
    assert len(workspace.history_records()) == 1
    assert calls == 1
