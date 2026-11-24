from __future__ import annotations

from dataclasses import replace
from threading import Event
from time import monotonic

import pytest
from PIL import Image

from refrain import runtime_control as control
from refrain.config import DisplayBackendConfiguration, DisplayOutputConfiguration
from refrain.display.coordinator import DisplayPublicationCoordinator, PublicationStatus, StagedTransientImages
from refrain.geometry import ResolvedOutputSpecification
from refrain.runtime_control import RuntimeControlClient, RuntimeControlServer, RuntimeProtocolError

SPEC = ResolvedOutputSpecification("16:9", (16, 9))
OUTPUTS = (
    DisplayOutputConfiguration("external", SPEC, audience="external"),
    DisplayOutputConfiguration("internal", SPEC, audience="internal"),
    DisplayOutputConfiguration("different", SPEC, audience="internal"),
)
CONFIG = DisplayBackendConfiguration("publish", outputs=OUTPUTS)
KEYS = {
    "external": OUTPUTS[0].prepared_image_key_for_qr("shared"),
    "internal": OUTPUTS[1].prepared_image_key_for_qr("shared"),
    "different": OUTPUTS[2].prepared_image_key_for_qr("different"),
}


def _images():
    return {
        KEYS["external"]: Image.new("RGB", SPEC.requested_output_size, (1, 0, 0)),
        KEYS["different"]: Image.new("RGB", SPEC.requested_output_size, (2, 0, 0)),
    }


def _metadata():
    shared = {"payload": "shared", "visibility": ["external"]}
    declarations = [
        shared,
        {"payload": "shared", "visibility": ["internal"]},
        {"payload": "different", "visibility": ["internal"]},
    ]
    base = {
        "checkpoint": {"content": {"qr": declarations}},
        "selection_revision": 1,
        "visibility": object(),
        "effective_presentation": {},
        "output_specification": SPEC,
    }
    return {
        KEYS["external"]: {**base, "rendered_qr": shared},
        KEYS["different"]: {**base, "rendered_qr": declarations[2]},
    }


def _wait_for_transient_cleanup(server):
    deadline = monotonic() + 5
    while server._transient_slot.locked() and monotonic() < deadline:
        Event().wait(0.01)
    assert not server._transient_slot.locked()


def test_scheduled_and_refresh_route_shared_pixels_and_prepared_metadata():
    seen = []

    class Backend:
        def publish_scheduled(self, destination, image, metadata):
            seen.append((destination.identifier, image.getpixel((0, 0))[0], metadata["rendered_qr"]["payload"]))

        def publish_transient(self, destination, image):
            raise AssertionError("scheduled publication must not use transient routing")

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((CONFIG,), lambda _: Backend(), retry=False)
    try:
        coordinator.publish_with_metadata((1, 0), _images(), _metadata(), destination_keys=KEYS)
        assert coordinator.wait_for_publication((1, 0), 5)
        assert coordinator.acknowledgements == {output.identifier: (1, 0) for output in OUTPUTS}
        operation = coordinator.force_scheduled_publication_with_metadata(
            (1, 0), _images(), _metadata(), destination_keys=KEYS
        )
        assert operation.wait(5).status is PublicationStatus.SUCCEEDED
        expected = [
            ("external", 1, "shared"),
            ("internal", 1, "shared"),
            ("different", 2, "different"),
        ]
        assert seen == expected * 2
    finally:
        coordinator.close()


def test_key_map_is_copied_and_changed_key_cannot_acknowledge_old_work():
    entered, release = Event(), Event()
    seen = []

    class Backend:
        def publish(self, destination, image):
            value = image.getpixel((0, 0))[0]
            seen.append((destination.identifier, value))
            if len(seen) == 1:
                entered.set()
                assert release.wait(5)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((CONFIG,), lambda _: Backend(), retry=False)
    mapping = dict(KEYS)
    try:
        coordinator.publish((1, 0), _images(), destination_keys=mapping)
        assert entered.wait(5)
        mapping["internal"] = KEYS["different"]
        changed = dict(KEYS)
        changed["external"] = KEYS["different"]
        coordinator.publish((1, 0), _images(), destination_keys=changed)
        stale = coordinator.force_scheduled_publication((1, 0), _images(), destination_keys=KEYS)
        assert stale.result.status is PublicationStatus.INVALID
        release.set()
        assert coordinator.wait_for_publication((1, 0), 5)
        assert seen == [("external", 1), ("external", 2), ("internal", 1), ("different", 2)]
        assert coordinator.acknowledgements == {output.identifier: (1, 0) for output in OUTPUTS}
    finally:
        release.set()
        coordinator.close()


@pytest.mark.parametrize(
    "mapping",
    [{}, {"external": SPEC}, {**KEYS, "external": ResolvedOutputSpecification("4:3", (16, 12))}, {**KEYS, "x": SPEC}],
)
def test_invalid_or_incomplete_key_maps_are_rejected(mapping):
    coordinator = DisplayPublicationCoordinator((CONFIG,), lambda _: None)
    images = _images()
    try:
        with pytest.raises(ValueError):
            coordinator.publish((1, 0), images, destination_keys=mapping)
        for image in images.values():
            with pytest.raises(ValueError):
                image.getpixel((0, 0))
    finally:
        coordinator.close()


@pytest.mark.parametrize("metadata", [False, True])
def test_runtime_refresh_forwards_destination_keys(tmp_path, metadata):
    seen = []

    class Backend:
        def publish(self, destination, image):
            seen.append((destination.identifier, image.getpixel((0, 0))[0]))

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((CONFIG,), lambda _: Backend(), retry=False)
    coordinator.publish((1, 0), _images(), destination_keys=KEYS)
    assert coordinator.wait_for_publication((1, 0), 5)
    seen.clear()

    def refresh(admit):
        return admit((1, 0), _images(), _metadata() if metadata else None, dict(KEYS))

    path = tmp_path / "endpoint.json"
    server = RuntimeControlServer(coordinator, path, refresh)
    try:
        server.start()
        assert RuntimeControlClient(path).refresh().status is PublicationStatus.SUCCEEDED
        assert seen == [("external", 1), ("internal", 1), ("different", 2)]
    finally:
        server.close()
        coordinator.close()


def test_runtime_transient_variants_and_audience_revalidation(tmp_path):
    seen = []
    change_audience = False

    class Backend:
        def publish(self, destination, image):
            seen.append((destination.identifier, image.getpixel((0, 0))[0]))

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((CONFIG,), lambda _: Backend(), retry=False)
    path = tmp_path / "endpoint.json"

    def admit_after_possible_change(destinations, specifications, images, admit):
        if change_audience:
            with coordinator._condition:
                state = coordinator._states["internal"]
                state.destination = replace(state.destination, audience="external")
        return admit(destinations, specifications, images)

    server = RuntimeControlServer(coordinator, path, lambda _: None, transient_admission=admit_after_possible_change)
    shared = Image.new("RGB", SPEC.requested_output_size, (1, 0, 0))
    different = Image.new("RGB", SPEC.requested_output_size, (2, 0, 0))
    try:
        server.start()
        client = RuntimeControlClient(path)
        discovered = client.discover()
        assert all(item["available"] == "unknown" for item in discovered)
        audiences = {item["identifier"]: item["audience"] for item in discovered}
        specifications = {item["identifier"]: item["output_specification"] for item in discovered}
        images = {"external": shared, "internal": shared, "different": different}
        result = client.publish_transient("@all", specifications, images, audiences=audiences)
        assert result.status is PublicationStatus.SUCCEEDED
        assert seen == [("external", 1), ("internal", 1), ("different", 2)]

        _wait_for_transient_cleanup(server)
        seen.clear()
        result = client.publish_transient("@all", specifications, {SPEC: shared}, audiences=audiences)
        assert result.status is PublicationStatus.SUCCEEDED
        assert seen == [("external", 1), ("internal", 1), ("different", 1)]
        _wait_for_transient_cleanup(server)
        seen.clear()
        with pytest.raises(RuntimeProtocolError, match="audiences are required"):
            client.publish_transient("@all", specifications, {SPEC: shared})
        with client._connect() as connection:
            control._send(
                connection,
                {
                    "version": control._VERSION,
                    "operation": "publish",
                    "preflight": True,
                    "target": "@all",
                    "specifications": {key: control._spec_to_wire(value) for key, value in specifications.items()},
                    "images": [{"specification": control._spec_to_wire(SPEC), "encoding": "png", "length": 1}],
                },
            )
            response = control._decode(control._receive(connection))
        assert response["status"] == "invalid"
        assert not seen

        _wait_for_transient_cleanup(server)
        audiences["internal"] = "external"
        result = client.publish_transient("@all", specifications, images, audiences=audiences)
        assert result.status is PublicationStatus.INVALID
        assert not seen

        _wait_for_transient_cleanup(server)
        audiences["internal"] = "internal"
        change_audience = True
        result = client.publish_transient("@all", specifications, images, audiences=audiences)
        assert result.status is PublicationStatus.INVALID
        assert not seen
    finally:
        shared.close()
        different.close()
        server.close()
        coordinator.close()


def test_transient_preflight_statuses_and_discovery_availability(tmp_path):
    seen = []
    window = DisplayOutputConfiguration("window", SPEC, audience="internal")
    configs = (CONFIG, DisplayBackendConfiguration("window", outputs=(window,)))

    class Backend:
        def publish(self, destination, image):
            seen.append(destination.identifier)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator(
        configs, lambda _: Backend(), retry=False, transient_capabilities={"different": False}
    )
    path = tmp_path / "endpoint.json"
    server = RuntimeControlServer(coordinator, path, lambda _: None)
    image = Image.new("RGB", SPEC.requested_output_size)
    try:
        server.start()
        client = RuntimeControlClient(path)
        statuses = {record["identifier"]: record for record in client.discover()}
        assert statuses["external"]["available"] == "unknown"
        assert statuses["window"]["available"] is False

        def request(identifier, *, audience="internal", specification=SPEC):
            return client.publish_transient(
                identifier, {identifier: specification}, {identifier: image}, audiences={identifier: audience}
            ).status

        assert request("missing") is PublicationStatus.DESTINATION_NOT_FOUND
        _wait_for_transient_cleanup(server)
        assert coordinator.withdraw_destination("external")
        assert request("external", audience="external") is PublicationStatus.WITHDRAWN
        _wait_for_transient_cleanup(server)
        assert request("different") is PublicationStatus.UNSUPPORTED
        _wait_for_transient_cleanup(server)
        other_spec = ResolvedOutputSpecification("4:3", SPEC.requested_output_size)
        assert request("different", specification=other_spec) is PublicationStatus.UNSUPPORTED
        _wait_for_transient_cleanup(server)
        assert request("internal", audience="external") is PublicationStatus.INVALID
        _wait_for_transient_cleanup(server)
        assert request("internal", specification=other_spec) is PublicationStatus.INVALID
        _wait_for_transient_cleanup(server)
        assert not seen

        for identifier in ("internal", "different", "window"):
            assert coordinator.withdraw_destination(identifier)
        assert client.publish_transient("@all", {}, {}, audiences={}).status is PublicationStatus.INVALID
        assert not seen
    finally:
        image.close()
        server.close()
        coordinator.close()


def test_staged_admission_rejects_missing_audience_associations(tmp_path):
    seen = []

    class Backend:
        def publish(self, destination, image):
            seen.append(destination.identifier)

        def close(self):
            pass

    coordinator = DisplayPublicationCoordinator((CONFIG,), lambda _: Backend(), retry=False)
    staged = StagedTransientImages(tmp_path)
    staged[SPEC] = tmp_path / "image.png"
    try:
        operation = coordinator.publish_transient("@all", {output.identifier: SPEC for output in OUTPUTS}, staged)
        assert operation.result.status is PublicationStatus.INVALID
        assert not seen
    finally:
        coordinator.close()
