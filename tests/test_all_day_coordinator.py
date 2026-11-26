from __future__ import annotations

import time
from datetime import date, timedelta
from threading import Event, Lock

from PIL import Image

from refrain import DisplayBackendConfiguration, DisplayOutputConfiguration, ResolvedOutputSpecification
from refrain.display import DisplayBackendUpdateError
from refrain.display import coordinator as coordinator_module
from refrain.display.coordinator import DisplayPublicationCoordinator, PublicationStatus
from refrain.publication_storage import PublicationStorageError

SPEC = ResolvedOutputSpecification("16:9", (16, 9))
DAY = date(2026, 11, 26)


def image(value: int) -> dict:
    return {SPEC: Image.new("RGB", SPEC.requested_output_size, (value, 0, 0))}


def wait_until(predicate) -> bool:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class Backend:
    def __init__(self) -> None:
        self.calls = []
        self.lock = Lock()
        self.entered = Event()
        self.release = Event()
        self.block_value = None
        self.failures = set()

    def publish(self, destination, picture) -> None:
        value = picture.getpixel((0, 0))[0]
        with self.lock:
            self.calls.append((destination.identifier, value))
        if value == self.block_value:
            self.entered.set()
            assert self.release.wait(5)
        if (destination.identifier, value) in self.failures:
            raise DisplayBackendUpdateError("failed")

    def close(self) -> None:
        pass


def coordinator(backend, clock, *identifiers):
    outputs = tuple(DisplayOutputConfiguration(key, SPEC, audience="internal") for key in identifiers)
    return DisplayPublicationCoordinator(
        (DisplayBackendConfiguration("publish", outputs=outputs),),
        lambda _: backend,
        retry=False,
        logical_date=lambda: clock[0],
    )


def push(owner, value, *identifiers, all_day=False):
    return owner.publish_transient(identifiers, {key: SPEC for key in identifiers}, image(value), all_day=all_day)


def test_hold_suppresses_and_coalesces_until_expiry_and_never_reactivates():
    clock, backend = [DAY], Backend()
    owner = coordinator(backend, clock, "one", "two")
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: all(value == (1, 0) for value in owner.acknowledgements.values()))
        assert push(owner, 2, "one", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        owner.publish((1, 1), image(3))
        assert wait_until(lambda: owner.acknowledgements["two"] == (1, 1))
        owner.publish((1, 2), image(4))
        assert wait_until(lambda: owner.acknowledgements["two"] == (1, 2))
        assert owner.acknowledgements["one"] == (1, 0)
        assert ("one", 3) not in backend.calls and ("one", 4) not in backend.calls
        clock[0] += timedelta(days=1)
        assert owner.expire_all_day_holds(clock[0])
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 2))
        assert ("one", 3) not in backend.calls
        clock[0] = DAY
        assert owner.expire_all_day_holds(clock[0])
        owner.publish((2, 0), image(5))
        assert wait_until(lambda: owner.acknowledgements["one"] == (2, 0))
    finally:
        owner.close()


def test_admitted_hold_protects_new_pending_and_busy_request():
    clock, backend = [DAY], Backend()
    backend.block_value = 2
    owner = coordinator(backend, clock, "one", "two")
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: all(value == (1, 0) for value in owner.acknowledgements.values()))
        operation = push(owner, 2, "one", all_day=True)
        assert backend.entered.wait(2)
        owner.publish((1, 1), image(3))
        assert push(owner, 4, "two").result.status is PublicationStatus.BUSY
        backend.release.set()
        assert operation.wait(2).status is PublicationStatus.SUCCEEDED
        assert wait_until(lambda: owner.acknowledgements["two"] == (1, 1))
        assert owner.acknowledgements["one"] == (1, 0)
        assert ("one", 3) not in backend.calls
    finally:
        backend.release.set()
        owner.close()


def test_partial_results_and_ordinary_success_clear_only_successful_holds():
    clock, backend = [DAY], Backend()
    owner = coordinator(backend, clock, "one", "two")
    try:
        assert push(owner, 1, "one", "two", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        backend.failures.add(("two", 2))
        result = push(owner, 2, "one", "two").wait(2)
        assert result.status is PublicationStatus.FAILED
        assert result.destinations["one"][0] is True and result.destinations["two"][0] is False
        owner.publish((1, 0), image(3))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        assert ("two", 3) not in backend.calls
        assert owner._states["one"].hold_date is None
        assert owner._states["two"].hold_date == DAY
        clock[0] += timedelta(days=1)
        assert owner.expire_all_day_holds(clock[0])
        assert owner._states["two"].hold_date is None
    finally:
        owner.close()


def test_refresh_rejection_preserves_holds_and_admission_clears_them():
    clock, backend = [DAY], Backend()
    owner = coordinator(backend, clock, "one")
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        assert push(owner, 2, "one", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        owner.publish((1, 1), image(3))
        assert owner.force_scheduled_publication((1, 0), image(4)).result.status is PublicationStatus.STALE_PRESENTATION
        assert owner._states["one"].hold_date == DAY
        backend.failures.add(("one", 5))
        assert owner.force_scheduled_publication((1, 1), image(5)).wait(2).status is PublicationStatus.FAILED
        assert owner._states["one"].hold_date is None
    finally:
        owner.close()


def test_date_change_during_inflight_hold_waits_for_reconciliation():
    clock, backend = [DAY], Backend()
    backend.block_value = 2
    owner = coordinator(backend, clock, "one")
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        operation = push(owner, 2, "one", all_day=True)
        assert backend.entered.wait(2)
        owner.publish((1, 1), image(3))
        clock[0] += timedelta(days=1)
        backend.release.set()
        assert operation.wait(2).status is PublicationStatus.SUCCEEDED
        assert ("one", 3) not in backend.calls
        clock[0] = DAY
        owner.publish((2, 0), image(4))
        assert owner.expire_all_day_holds(clock[0])
        assert wait_until(lambda: owner.acknowledgements["one"] == (2, 0))
        assert ("one", 3) not in backend.calls
    finally:
        backend.release.set()
        owner.close()


def test_stale_reconciliation_cannot_release_expired_hold():
    clock, backend = [DAY], Backend()
    owner = coordinator(backend, clock, "one")
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        assert push(owner, 2, "one", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        owner.publish((1, 1), image(3))
        clock[0] += timedelta(days=1)
        assert not owner.expire_all_day_holds(DAY)
        assert ("one", 3) not in backend.calls
        owner.publish((2, 0), image(4))
        assert owner.expire_all_day_holds(clock[0])
        assert wait_until(lambda: owner.acknowledgements["one"] == (2, 0))
        assert ("one", 3) not in backend.calls
    finally:
        owner.close()


def test_refresh_of_held_pending_presentation_does_not_repeat_it():
    clock, backend = [DAY], Backend()
    owner = coordinator(backend, clock, "one")
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        assert push(owner, 2, "one", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        owner.publish((1, 1), image(3))
        assert owner.force_scheduled_publication((1, 1), image(4)).wait(2).status is PublicationStatus.SUCCEEDED
        assert owner.acknowledgements["one"] == (1, 1)
        assert backend.calls == [("one", 1), ("one", 2), ("one", 4)]
    finally:
        owner.close()


def test_refresh_rechecks_reconciled_date_before_clearing_hold():
    clock, backend = [DAY], Backend()
    owner = coordinator(backend, clock, "one")
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        assert push(owner, 2, "one", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        clock[0] += timedelta(days=1)
        result = owner.force_scheduled_publication((1, 0), image(3), expected_date=DAY)
        assert result.result.status is PublicationStatus.STALE_PRESENTATION
        assert owner._states["one"].hold_date == DAY
        assert backend.calls == [("one", 1), ("one", 2)]
    finally:
        owner.close()


def test_refresh_rechecks_complete_identity_before_clearing_hold():
    clock, backend = [DAY], Backend()
    owner = coordinator(backend, clock, "one")
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        assert push(owner, 2, "one", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        result = owner.force_scheduled_publication((1, 0), image(3), expected_date=DAY, admission_check=lambda: False)
        assert result.result.status is PublicationStatus.STALE_PRESENTATION
        assert owner._states["one"].hold_date == DAY
        assert backend.calls == [("one", 1), ("one", 2)]
    finally:
        owner.close()


def test_failed_all_day_renewal_retains_existing_hold():
    clock, backend = [DAY], Backend()
    owner = coordinator(backend, clock, "one", "two")
    try:
        assert push(owner, 1, "one", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        backend.failures.add(("one", 2))
        result = push(owner, 2, "one", "two", all_day=True).wait(2)
        assert result.status is PublicationStatus.FAILED
        assert result.destinations["one"][0] is False and result.destinations["two"][0] is True
        assert owner._states["one"].hold_date == owner._states["two"].hold_date == DAY
    finally:
        owner.close()


def test_unconfirmed_filesystem_result_preserves_hold_and_is_not_retried():
    clock = [DAY]

    class UncertainBackend(Backend):
        def publish(self, destination, picture):
            if picture.getpixel((0, 0))[0] == 2:
                self.calls.append((destination.identifier, 2))
                try:
                    raise PublicationStorageError("outcome uncertain", published=True)
                except PublicationStorageError as error:
                    raise DisplayBackendUpdateError("cannot confirm commit") from error
            super().publish(destination, picture)

    backend = UncertainBackend()
    owner = coordinator(backend, clock, "one")
    try:
        assert push(owner, 1, "one", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        result = push(owner, 2, "one").wait(2)
        assert result.status is PublicationStatus.UNCONFIRMED
        assert result.destinations["one"][0] is None
        assert owner._states["one"].hold_date == DAY
        assert backend.calls == [("one", 1), ("one", 2)]
        assert push(owner, 3, "one").wait(2).status is PublicationStatus.SUCCEEDED
        assert owner._states["one"].hold_date is None
    finally:
        owner.close()


def test_mixed_uncertain_and_failed_results_preserve_both_holds():
    clock = [DAY]

    class MixedBackend(Backend):
        def publish(self, destination, picture):
            if picture.getpixel((0, 0))[0] == 2:
                if destination.identifier == "one":
                    try:
                        raise PublicationStorageError("outcome uncertain", published=True)
                    except PublicationStorageError as error:
                        raise DisplayBackendUpdateError("cannot confirm commit") from error
                raise DisplayBackendUpdateError("definite failure")
            super().publish(destination, picture)

    backend = MixedBackend()
    owner = coordinator(backend, clock, "one", "two")
    try:
        assert push(owner, 1, "one", "two", all_day=True).wait(2).status is PublicationStatus.SUCCEEDED
        result = push(owner, 2, "one", "two", all_day=True).wait(2)
        assert result.status is PublicationStatus.FAILED
        assert result.destinations["one"][0] is None
        assert result.destinations["two"][0] is False
        assert owner._states["one"].hold_date == owner._states["two"].hold_date == DAY
    finally:
        owner.close()


def test_scheduled_failure_retains_existing_retry_behavior():
    clock = [DAY]

    class RetryBackend(Backend):
        def publish(self, destination, picture):
            self.calls.append((destination.identifier, picture.getpixel((0, 0))[0]))
            if len(self.calls) == 1:
                try:
                    raise PublicationStorageError("outcome uncertain", published=True)
                except PublicationStorageError as error:
                    raise DisplayBackendUpdateError("cannot confirm commit") from error

    backend = RetryBackend()
    output = DisplayOutputConfiguration("one", SPEC, audience="internal")
    owner = DisplayPublicationCoordinator(
        (DisplayBackendConfiguration("publish", outputs=(output,)),),
        lambda _: backend,
        logical_date=lambda: clock[0],
    )
    try:
        owner.publish((1, 0), image(1))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        assert backend.calls == [("one", 1), ("one", 1)]
    finally:
        owner.close()


def test_resolved_failure_releases_its_backend_while_another_remains_blocked(monkeypatch):
    monkeypatch.setattr(coordinator_module, "_MAX_RETRY_ATTEMPTS", 1)
    clock = [DAY]
    fast, blocked = Backend(), Backend()
    fast.failures.add(("one", 2))
    blocked.block_value = 2
    configurations = (
        DisplayBackendConfiguration("window", outputs=(DisplayOutputConfiguration("one", SPEC, audience="internal"),)),
        DisplayBackendConfiguration("publish", outputs=(DisplayOutputConfiguration("two", SPEC, audience="internal"),)),
    )
    owner = DisplayPublicationCoordinator(
        configurations,
        lambda config: fast if config.type == "window" else blocked,
        logical_date=lambda: clock[0],
    )
    try:
        operation = push(owner, 2, "one", "two", all_day=True)
        assert blocked.entered.wait(2)
        assert wait_until(lambda: operation.result.destinations["one"][0] is False)
        owner.publish((1, 0), image(3))
        assert wait_until(lambda: owner.acknowledgements["one"] == (1, 0))
        assert owner.acknowledgements["two"] is None
        assert push(owner, 4, "one").result.status is PublicationStatus.BUSY
        blocked.release.set()
        assert operation.wait(2).status is PublicationStatus.FAILED
        assert ("two", 3) not in blocked.calls
    finally:
        blocked.release.set()
        owner.close()


def test_invalid_hold_flag_and_missing_clock_rejected():
    backend = Backend()
    output = DisplayOutputConfiguration("one", SPEC, audience="internal")
    owner = DisplayPublicationCoordinator(
        (DisplayBackendConfiguration("publish", outputs=(output,)),), lambda _: backend
    )
    try:
        assert push(owner, 1, "one", all_day=True).result.status is PublicationStatus.INVALID
        assert push(owner, 1, "one", all_day=1).result.status is PublicationStatus.INVALID
        assert backend.calls == []
    finally:
        owner.close()
