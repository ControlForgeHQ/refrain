from __future__ import annotations

import builtins
import json
import signal
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace

import pytest
from PIL import Image

import refrain.__main__ as cli
import refrain.application as application
from refrain.artifacts import PreparedImageArtifactSet
from refrain.display import DisplayBackendInitializationError, DisplayBackendUpdateError
from refrain.display.coordinator import DisplayPublicationCoordinator
from refrain.persistence import PersistentStateStore, StateCommitError, StateRecoveryError
from refrain.preparation import DailyImagePreparationError

_CONFIG = """\
general:
  day_start: "06:00"
content:
  directory: "content"
reveal:
  source: "12:00"
  attribution: "18:00"
display:
  backends:
    - type: "window"
information_view:
  duration: 60
layout:
  presentation_region: {x: 0.1, y: 0.15, width: 0.8, height: 0.55}
  fonts:
    default: ["lora", "libre-baskerville"]
  backgrounds:
    default: ["none", "canvas"]
  text: {min_font_size: 28, max_font_size: 100}
"""
_START = datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc)


class DemoClock(Event):
    def __init__(self, *, waits: int = 3, steps=()) -> None:
        super().__init__()
        self.now = _START
        self.elapsed = 0.0
        self.wall_reads = 0
        self.waits: list[float] = []
        self.limit = waits
        self.steps = iter(steps)
        self.on_wait = None

    def wall(self):
        self.wall_reads += 1
        return self.now

    def monotonic(self):
        return self.elapsed

    def wait(self, timeout=None):
        assert timeout is not None and 0 < timeout <= 60
        self.waits.append(timeout)
        if self.on_wait is not None:
            self.on_wait(timeout)
        self.elapsed += next(self.steps, timeout)
        self.now += timedelta(days=10 if len(self.waits) % 2 else -20)
        if len(self.waits) >= self.limit:
            self.set()
        return self.is_set()


class DemoWorkspace:
    def __init__(self, root: Path, monkeypatch) -> None:
        self.root = root
        self.config = root / "config.yaml"
        self.config.write_text(_CONFIG, encoding="utf-8")
        self.content = root / "content"
        self.content.mkdir()
        self.sessions: list[Path] = []
        self.coordinators = []
        self.stores = []
        self.selected = []
        self.prepared = []
        self.publications = []
        self.clock = DemoClock()
        self.on_publish = None
        self.on_ack = None
        self.cleanup_error = False
        workspace = self

        class LocalSession:
            def __init__(self, **kwargs):
                self.session = TemporaryDirectory(dir=root, **kwargs)
                self.name = self.session.name
                workspace.sessions.append(Path(self.name))

            def cleanup(self):
                self.session.cleanup()
                if workspace.cleanup_error:
                    raise OSError("injected cleanup failure")

        class RecordingStore(PersistentStateStore):
            def __init__(self, path):
                super().__init__(path)
                workspace.stores.append(self)

        real_selection = application._select_snapshot
        real_recovery = application.recover_prepared_daily_images

        def select(*args, **kwargs):
            result = real_selection(*args, **kwargs)
            workspace.selected.append(result)
            return result

        def recover(state, store, stages, *args, **kwargs):
            assert workspace.stores[-1].load() == state
            result = real_recovery(state, store, stages, *args, **kwargs)
            workspace.prepared.append((state, stages, result))
            return result

        class RecordingCoordinator:
            def __init__(self, configurations, factory, **kwargs):
                self.configurations = configurations
                self.desired_identity = None
                self.all_unavailable = False
                self.acknowledged = {}
                self.closed = 0
                self.requested = []
                workspace.coordinators.append(self)

            def publish(self, identity, image):
                try:
                    state = workspace.stores[-1].load()
                    workspace.publications.append((identity, workspace.clock.elapsed, state, image.size))
                    self.requested.append(identity)
                    self.desired_identity = identity
                    if workspace.on_publish is not None:
                        workspace.on_publish(self, identity)
                finally:
                    image.close()

            def wait_for_any_publication(self, identity, *, cancellation_event):
                assert cancellation_event is workspace.clock
                if workspace.on_ack is not None:
                    return workspace.on_ack(self, identity)
                self.acknowledged.setdefault(identity, workspace.clock.elapsed)
                return True

            def first_successful_publication_time(self, identity):
                return self.acknowledged.get(identity)

            def close(self):
                self.closed += 1

        monkeypatch.setattr(application, "TemporaryDirectory", LocalSession)
        monkeypatch.setattr(application, "PersistentStateStore", RecordingStore)
        monkeypatch.setattr(application, "_select_snapshot", select)
        monkeypatch.setattr(application, "recover_prepared_daily_images", recover)
        monkeypatch.setattr(application, "DisplayPublicationCoordinator", RecordingCoordinator)
        monkeypatch.setattr(application, "prepare_information_view", self.forbidden)
        monkeypatch.setattr(application, "DisplayDayBoundaryObserver", self.forbidden)
        monkeypatch.setattr(application, "wait_for_scheduling_event", self.forbidden)

    @staticmethod
    def forbidden(*args, **kwargs):
        pytest.fail("demo must not use normal scheduling or the information view")

    def entry(self, name="ordinary", *, metadata=True, extra="", quotations=None):
        quotations = quotations or ["First quotation.", "Second quotation."]
        body = 'source: "A Book"\nattribution: "An Author"\n' if metadata else ""
        (self.content / f"{name}.yaml").write_text(
            f'id: "{name}"\n{body}{extra}quotations:\n' + "".join(f"  - {json.dumps(text)}\n" for text in quotations),
            encoding="utf-8",
        )

    def run(self, interval=2.5, **kwargs):
        return application.run_demo(
            self.config,
            interval,
            shutdown_event=self.clock,
            wall_clock=self.clock.wall,
            monotonic_clock=self.clock.monotonic,
            random_source=Random(3),
            **kwargs,
        )

    def assert_clean(self):
        assert self.sessions and all(not path.exists() for path in self.sessions)
        assert all(coordinator.closed == 1 for coordinator in self.coordinators)


@pytest.fixture
def demo(tmp_path, monkeypatch):
    return DemoWorkspace(tmp_path, monkeypatch)


@pytest.mark.parametrize("value", ["5", "0.125"])
def test_cli_demo_accepts_interval_without_persistence_paths(monkeypatch, tmp_path, value):
    calls = []
    handlers = {}
    config = tmp_path / "config.yaml"
    config.write_text(_CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def install(signum, handler):
        previous = handlers.get(signum, signal.SIG_DFL)
        handlers[signum] = handler
        return previous

    def run(config, interval, **kwargs):
        calls.append((config, interval, kwargs))
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        assert kwargs["shutdown_event"].is_set()

    monkeypatch.setattr(cli.signal, "signal", install)
    monkeypatch.setattr(cli, "run_demo", run)
    monkeypatch.setattr(cli, "run_application", DemoWorkspace.forbidden)
    monkeypatch.setattr(cli, "run_startup", DemoWorkspace.forbidden)
    assert cli.main(["--config", config.name, "--demo", value]) == 0
    assert calls[0][:2] == (config.name, float(value))
    assert set(calls[0][2]) == {"shutdown_event", "history_segment_size", "history_max_segments"}
    assert handlers == {signal.SIGINT: signal.SIG_DFL, signal.SIGTERM: signal.SIG_DFL}


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "not-seconds"])
def test_cli_rejects_invalid_intervals(monkeypatch, capsys, value):
    monkeypatch.setattr(cli, "run_demo", DemoWorkspace.forbidden)
    with pytest.raises(SystemExit) as error:
        cli.main(["--config", "config.yaml", f"--demo={value}"])
    assert error.value.code == 2
    assert "positive finite number of seconds" in capsys.readouterr().err


def test_cli_once_excludes_demo(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--config", "config.yaml", "--once", "--demo", "1"])
    assert error.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("mode", [[], ["--once"]])
def test_normal_cli_uses_standard_persistence_paths_without_arguments(mode, tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(_CONFIG, encoding="utf-8")
    state = tmp_path / "state" / "state.json"
    artifacts = tmp_path / "cache" / "artifacts"
    paths = SimpleNamespace(config_file=config, state_file=state, artifacts_directory=artifacts)
    monkeypatch.setattr(cli, "resolve_application_paths", lambda: paths)
    monkeypatch.setattr(cli.signal, "signal", lambda *args: signal.SIG_DFL)
    calls = []

    def run(config_file, state_file, artifact_root, **kwargs):
        calls.append((config_file, state_file, artifact_root, kwargs))
        return SimpleNamespace(
            state=SimpleNamespace(revision=1, snapshot=SimpleNamespace(display_date=date(2026, 3, 10))),
            selected_initial_quotation=True,
            presented_stage=0,
        )

    monkeypatch.setattr(cli, "run_application", run)
    monkeypatch.setattr(cli, "run_startup", run)
    assert cli.main(mode) == 0
    assert calls[0][:3] == (config, state, artifacts)
    assert calls[0][3]["history_path"] is None


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_direct_demo_rejects_invalid_interval_before_loading_config(value):
    with pytest.raises(application.ApplicationError, match="positive finite"):
        application.run_demo("nonexistent.yaml", value)


@pytest.mark.parametrize(
    ("metadata", "extra", "expected"),
    [
        (True, "", [(True, False, False), (True, True, False), (True, True, True)]),
        (True, 'reveal: {source: "12:00", attribution: "12:00"}\n', [(True, False, False), (True, True, True)]),
        (False, "", [(True, False, False)]),
    ],
)
def test_real_pipeline_uses_complete_canonical_stages_and_cleans_session(demo, metadata, extra, expected):
    demo.entry(metadata=metadata, extra=extra)
    demo.clock.limit = len(expected) + 1
    demo.run()
    assert [identity for identity, *_ in demo.publications] == [
        *((1, stage) for stage in range(len(expected))),
        (2, 0),
    ]
    assert [when for _, when, *_ in demo.publications] == [2.5 * n for n in range(len(expected) + 1)]
    assert all(size == (1600, 1200) for *_, size in demo.publications)
    state, stages, _ = demo.prepared[0]
    assert [(stage.quotation, stage.source, stage.attribution) for stage in stages] == expected
    assert state.snapshot.display_date == date(2026, 3, 9)
    assert [state.highest_reveal_stage for identity, _, state, _ in demo.publications if identity[0] == 1] == list(
        range(len(expected))
    )
    assert len(demo.selected) == 2 and len(demo.prepared) == 2
    demo.assert_clean()


def test_demo_pipeline_uses_registered_decoration_and_committed_region(demo):
    overlay = demo.root / "assets" / "decorations" / "overlay.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGBA", (1600, 1200), (200, 20, 40, 128)).save(overlay)
    demo.config.write_text(
        _CONFIG.replace(
            '  backgrounds:\n    default: ["none", "canvas"]',
            '  backgrounds:\n    default: ["none"]\n'
            "  decorations:\n"
            '    available: {demo-overlay: {image: "overlay.png", '
            "presentation_region: {x: 0.2, y: 0.3, width: 0.6, height: 0.4}}}\n"
            '    default: ["demo-overlay"]',
        ),
        encoding="utf-8",
    )
    demo.entry(metadata=False)
    demo.clock.limit = 2
    pixels = []

    def inspect_prepared_stage(_coordinator, _identity):
        if not pixels:
            with demo.prepared[0][2].load_stage(0) as image:
                pixels.append(image.getpixel((10, 10)))

    demo.on_publish = inspect_prepared_stage

    demo.run()

    state, _, _ = demo.prepared[0]
    assert state.snapshot.decoration_identifier == "demo-overlay"
    assert dict(state.snapshot.layout["presentation_region"]) == {
        "x": 0.2,
        "y": 0.3,
        "width": 0.6,
        "height": 0.4,
    }
    assert pixels[0] == (227, 137, 147)
    demo.assert_clean()


def test_fixed_timezone_date_selection_rules_repetition_and_resources(demo):
    demo.entry("ordinary", quotations=["Ordinary."], extra="priority: 999\n")
    demo.entry(
        "special",
        quotations=["Special one.", "Special two."],
        extra='priority: 10\neligibility:\n  - {year: 2026, month: 3, day: 9}\nfont: "lora"\nbackground: "none"\n',
    )
    demo.entry(
        "lower-priority",
        quotations=["Special lower priority."],
        extra="priority: 1\neligibility:\n  - {year: 2026, month: 3, day: 9}\n",
    )
    demo.clock.limit = 10
    histories = []
    retained = []
    history_records = []

    def inspect(timeout):
        state = demo.stores[-1].load()
        histories.append(state.repetition_history)
        retained.append(list((demo.sessions[-1] / "artifacts").glob("revision-*")))
        history_records.append(
            [
                json.loads(line)
                for line in (demo.sessions[-1] / "global-history.jsonl").read_text(encoding="utf-8").splitlines()
            ]
        )

    demo.clock.on_wait = inspect
    demo.run(history_segment_size=256, history_max_segments=1)
    snapshots = [snapshot for _, snapshot in demo.selected]
    assert [proposal.base_revision for proposal, _ in demo.selected] == [0, 1, 2, 3]
    assert snapshots[0].quotation_identity != snapshots[1].quotation_identity
    assert snapshots[2].quotation_text == "Special lower priority."
    assert snapshots[3].quotation_text in {"Special one.", "Special two."}
    assert all(snapshot.display_date == date(2026, 3, 9) for snapshot in snapshots)
    assert all("Ordinary" not in snapshot.quotation_text for snapshot in snapshots)
    assert demo.clock.wall_reads == 1
    assert len(histories[0]) == 1 and len(histories[3]) == 2 and len(histories[6]) == 3
    assert len(histories[9]) == 1
    for revision in (1, 2, 4):
        states = [state for (identity, _, state, _) in demo.publications if identity[0] == revision]
        assert all(state.snapshot.font_identifier == "lora" for state in states)
        assert all(state.snapshot.background_identifier == "none" for state in states)
        assert all(state.snapshot == states[0].snapshot for state in states)
    assert all(len(paths) == 1 for paths in retained)
    assert all(len(records) == 1 for records in history_records)
    assert history_records[-1][0]["revision"] == 4
    assert snapshots[2].font_identifier in {"lora", "libre-baskerville"}
    assert snapshots[2].background_identifier in {"none", "canvas"}
    demo.assert_clean()


def test_cli_supplied_production_paths_are_never_read_or_modified(demo, monkeypatch):
    demo.entry(metadata=False)
    production = demo.root / "production"
    production.mkdir()
    paths = [production / "state.json", production / "global-history.jsonl", production / "stage-0.png"]
    for number, path in enumerate(paths):
        path.write_bytes(b"production sentinel\x00" + bytes([number]))
    original = {path: path.read_bytes() for path in paths}
    real_path_open = Path.open
    real_open = builtins.open

    def guard_path(path, *args, **kwargs):
        assert not path.is_relative_to(production), "demo accessed production storage"
        return real_path_open(path, *args, **kwargs)

    def guard_open(path, *args, **kwargs):
        if isinstance(path, (str, Path)):
            assert not Path(path).absolute().is_relative_to(production), "demo accessed production storage"
        return real_open(path, *args, **kwargs)

    def run(config, interval, **kwargs):
        assert not {"state_path", "artifact_root", "history_path"} & kwargs.keys()
        demo.run(interval)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guard_path)
        patch.setattr(builtins, "open", guard_open)
        patch.setattr(cli, "run_demo", run)
        assert (
            cli.main(
                [
                    "--config",
                    str(demo.config),
                    "--demo",
                    "0.25",
                    "--state",
                    str(paths[0]),
                    "--history",
                    str(paths[1]),
                    "--artifacts",
                    str(production),
                ]
            )
            == 0
        )
    assert {path: path.read_bytes() for path in paths} == original
    assert sorted(production.iterdir()) == sorted(paths)
    demo.assert_clean()


@pytest.mark.parametrize("observation_delay", [0, 2])
def test_preparation_and_ack_latency_do_not_consume_interval(demo, monkeypatch, observation_delay):
    demo.entry()
    recover = application.recover_prepared_daily_images

    def slow_prepare(*args, **kwargs):
        result = recover(*args, **kwargs)
        demo.clock.elapsed += 100
        return result

    def delayed_ack(coordinator, identity):
        demo.clock.elapsed += 50
        coordinator.acknowledged[identity] = demo.clock.elapsed
        demo.clock.elapsed += observation_delay
        return True

    monkeypatch.setattr(application, "recover_prepared_daily_images", slow_prepare)
    demo.on_ack = delayed_ack
    demo.clock.limit = 4
    demo.run(5)
    assert [when for _, when, *_ in demo.publications] == [100, 155, 210, 365]
    assert demo.clock.waits == [5 - observation_delay] * 4
    demo.assert_clean()


def test_short_interruptible_waits_never_advance_early_and_wall_jumps_do_not_matter(demo):
    demo.entry()
    demo.clock = DemoClock(waits=4, steps=[1, 2, 2, 0])
    demo.run(5)
    assert demo.clock.waits == [5, 4, 2, 5]
    assert [identity for identity, *_ in demo.publications] == [(1, 0), (1, 1)]
    assert [when for _, when, *_ in demo.publications] == [0, 5]
    assert demo.clock.wall_reads == 1
    demo.assert_clean()


def test_long_interval_uses_bounded_waits_and_shutdown_stops_progression(demo):
    demo.entry()
    demo.clock.limit = 3
    demo.run(125)
    assert demo.clock.waits == [60, 60, 5]
    assert [identity for identity, *_ in demo.publications] == [(1, 0)]
    demo.assert_clean()


def test_unacknowledged_stage_neither_waits_interval_nor_selects_again(demo):
    demo.entry()
    attempts = []

    def unacknowledged(coordinator, identity):
        attempts.append(identity)
        if len(attempts) == 3:
            demo.clock.set()
        return False

    demo.on_ack = unacknowledged
    demo.run()
    assert attempts == [(1, 0)] * 3
    assert len(demo.selected) == 1
    assert len(demo.publications) == 1 and not demo.clock.waits
    demo.assert_clean()


@pytest.mark.parametrize("failure", ["preparation", "artifact-load", "publication", "commit", "reveal-commit"])
def test_recoverable_operations_retry_same_selection_and_stage(demo, monkeypatch, failure):
    demo.entry()
    failed = False

    if failure == "preparation":
        original = application.recover_prepared_daily_images

        def operation(*args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise DailyImagePreparationError("injected preparation failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(application, "recover_prepared_daily_images", operation)
    elif failure == "artifact-load":
        original = PreparedImageArtifactSet.load_stage

        def operation(self, stage):
            nonlocal failed
            if stage == 1 and not failed and demo.coordinators[-1].desired_identity == (1, 0):
                assert [identity for identity, *_ in demo.publications] == [(1, 0)]
                assert demo.stores[-1].load().highest_reveal_stage == 1
                failed = True
                self.stage_paths[stage].unlink()
            return original(self, stage)

        monkeypatch.setattr(PreparedImageArtifactSet, "load_stage", operation)
    elif failure == "publication":

        def publish(coordinator, identity):
            nonlocal failed
            if identity == (1, 1) and not failed:
                failed = True
                coordinator.desired_identity = None
                raise application._RetryableApplicationError("injected publication failure")

        demo.on_publish = publish
    else:
        name = "commit" if failure == "commit" else "advance_reveal_progress"
        original = getattr(application.PersistentStateStore, name)

        def operation(self, *args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise StateCommitError("injected storage failure")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(application.PersistentStateStore, name, operation)
    demo.clock.limit = 4
    demo.run()
    assert failed and len(demo.selected) == 1
    identities = [identity for identity, *_ in demo.publications]
    assert identities == ([(1, 0), (1, 1), (1, 1), (1, 2)] if failure == "publication" else [(1, 0), (1, 1), (1, 2)])
    assert demo.clock.waits.count(1) == 1 and demo.clock.waits.count(2.5) == 3
    assert all(state.revision == 1 for _, _, state, _ in demo.publications)
    if failure == "artifact-load":
        assert len(demo.prepared) == 2
        assert demo.prepared[0][0].snapshot == demo.prepared[1][0].snapshot
        assert demo.prepared[0][2].stage_paths != demo.prepared[1][2].stage_paths
    demo.assert_clean()


def test_uncertain_published_commit_recovers_after_transient_reload_failure(demo, monkeypatch):
    demo.entry()
    original_commit = application.PersistentStateStore.commit
    original_load = application.PersistentStateStore.load
    committed = False
    reload_failed = False
    commit_calls = []
    commit_arguments = []

    def commit(self, proposal, snapshot):
        nonlocal committed
        commit_calls.append(proposal.base_revision)
        commit_arguments.append((proposal, snapshot))
        state = original_commit(self, proposal, snapshot)
        if not committed:
            committed = True
            raise StateCommitError("published but sync failed", published=True)
        return state

    def load(self):
        nonlocal reload_failed
        if committed and not reload_failed:
            reload_failed = True
            try:
                raise OSError("transient reload failure")
            except OSError as cause:
                raise StateRecoveryError("state temporarily inaccessible") from cause
        return original_load(self)

    monkeypatch.setattr(application.PersistentStateStore, "commit", commit)
    monkeypatch.setattr(application.PersistentStateStore, "load", load)
    demo.clock.limit = 4
    history_lengths = []

    def inspect(timeout):
        history = demo.sessions[-1] / "global-history.jsonl"
        if history.exists():
            history_lengths.append(len(history.read_text(encoding="utf-8").splitlines()))

    demo.clock.on_wait = inspect
    demo.run()
    assert committed and reload_failed
    assert commit_calls == [0, 0]
    assert commit_arguments[0][0] is commit_arguments[1][0]
    assert commit_arguments[0][1] is commit_arguments[1][1]
    assert commit_arguments[0] == demo.selected[0]
    assert len(demo.selected) == 1
    assert [identity for identity, *_ in demo.publications] == [(1, 0), (1, 1), (1, 2)]
    assert demo.clock.waits == [1, 2.5, 2.5, 2.5]
    assert history_lengths == [1, 1, 1]
    demo.assert_clean()


def test_fresh_invocations_start_at_revision_one_with_empty_history(demo):
    demo.entry(metadata=False)
    recorded = []

    def inspect(timeout):
        state = demo.stores[-1].load()
        records = (demo.sessions[-1] / "global-history.jsonl").read_text(encoding="utf-8").splitlines()
        recorded.append((state, [json.loads(line) for line in records]))

    for _ in range(2):
        demo.clock = DemoClock(waits=1)
        demo.clock.on_wait = inspect
        demo.run()
    assert demo.sessions[0] != demo.sessions[1]
    assert [state.revision for state, _ in recorded] == [1, 1]
    assert all(len(state.repetition_history) == 1 and len(records) == 1 for state, records in recorded)
    assert [proposal.base_revision for proposal, _ in demo.selected] == [0, 0]
    demo.assert_clean()


def test_cleanup_oserror_does_not_mask_primary_error(demo, monkeypatch, caplog):
    demo.entry()
    demo.cleanup_error = True

    def broken(*args, **kwargs):
        raise application.ApplicationError("primary fatal failure")

    monkeypatch.setattr(application, "_select_snapshot", broken)
    with pytest.raises(application.ApplicationError, match="primary fatal failure"):
        demo.run()
    assert "Cannot remove temporary demo storage" in caplog.text
    demo.assert_clean()


@pytest.mark.parametrize("termination", [signal.SIGINT, signal.SIGTERM])
def test_cli_signal_stops_real_demo_and_restores_handlers(demo, monkeypatch, termination):
    demo.entry()
    handlers = {}

    def install(signum, handler):
        previous = handlers.get(signum, signal.SIG_DFL)
        handlers[signum] = handler
        return previous

    def run(config, interval, **kwargs):
        assert kwargs["shutdown_event"] is not demo.clock
        demo.clock.on_wait = lambda timeout: handlers[termination](termination, None)

        def wait(timeout):
            demo.clock.wait(timeout)
            if kwargs["shutdown_event"].is_set():
                demo.clock.set()
            return demo.clock.is_set()

        demo.run(interval, wait=wait)

    monkeypatch.setattr(cli.signal, "signal", install)
    monkeypatch.setattr(cli, "run_demo", run)
    assert cli.main(["--config", str(demo.config), "--demo", "1"]) == 0
    assert [identity for identity, *_ in demo.publications] == [(1, 0)]
    assert handlers == {signal.SIGINT: signal.SIG_DFL, signal.SIGTERM: signal.SIG_DFL}
    demo.assert_clean()


@pytest.mark.parametrize("other", ["blocked", "unavailable"])
def test_actual_coordinator_healthy_backend_progresses_independently(demo, monkeypatch, other):
    demo.entry()
    demo.config.write_text(_CONFIG.replace('    - type: "window"', '    - type: "window"\n    - type: "image-server"'))
    entered = Event()
    release = Event()
    caught_up = Event()
    healthy = []
    slow = []
    closed = []
    coordinators = []

    class Backend:
        def __init__(self, name):
            self.name = name

        def update(self, image):
            identity = coordinators[0].desired_identity
            if self.name == "image-server":
                slow.append(identity)
                if len(slow) == 1:
                    entered.set()
                    assert release.wait(5), "test failed to release blocked backend"
                else:
                    caught_up.set()
            else:
                healthy.append(identity)

        def close(self):
            closed.append(self.name)

    def factory(configuration):
        if configuration.type == "image-server" and other == "unavailable":
            entered.set()
            raise DisplayBackendInitializationError("unsupported destination", recoverable=False)
        return Backend(configuration.type)

    class TrackingCoordinator(DisplayPublicationCoordinator):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            coordinators.append(self)

        def close(self):
            release.set()
            super().close()

    monkeypatch.setattr(application, "DisplayPublicationCoordinator", TrackingCoordinator)

    def observe(timeout):
        assert entered.wait(5)
        if len(demo.clock.waits) == 3 and other == "blocked":
            release.set()
            assert caught_up.wait(5)

    demo.clock.on_wait = observe
    demo.run(1, backend_factory=factory)
    assert healthy == [(1, 0), (1, 1), (1, 2)]
    if other == "blocked":
        assert slow == [(1, 0), (1, 2)]
        assert sorted(closed) == ["image-server", "window"]
    else:
        assert closed == ["window"]
    assert not coordinators[0].all_unavailable
    assert coordinators[0].desired_identity is None
    assert all(not path.exists() for path in demo.sessions)


def test_actual_coordinator_all_terminal_backends_stop_selection(demo, monkeypatch):
    demo.entry()
    calls = []

    def factory(configuration):
        calls.append(configuration.type)

        class BrokenBackend:
            def update(self, image):
                raise DisplayBackendUpdateError("destination permanently unavailable", recoverable=False)

            def close(self):
                calls.append("closed")

        return BrokenBackend()

    monkeypatch.setattr(application, "DisplayPublicationCoordinator", DisplayPublicationCoordinator)
    with pytest.raises(application.ApplicationError, match="all configured display destinations are unavailable"):
        demo.run(backend_factory=factory)
    assert len(demo.selected) == 1 and len(demo.prepared) == 1
    assert calls == ["window", "closed"]
    assert not demo.clock.waits
    assert all(not path.exists() for path in demo.sessions)


@pytest.mark.parametrize("phase", ["initialization", "update"])
def test_actual_coordinator_recoverable_backend_error_retries_before_ack(demo, monkeypatch, phase):
    demo.entry()
    factory_calls = []
    updates = []
    successful_update_times = []
    delays = []
    closed = []
    coordinators = []

    class Backend:
        def update(self, image):
            identity = coordinators[0].desired_identity
            updates.append(identity)
            if phase == "update" and len(updates) == 1:
                demo.clock.elapsed += 40
                raise DisplayBackendUpdateError("temporary update failure")
            successful_update_times.append(demo.clock.elapsed)

        def close(self):
            closed.append(True)

    def factory(configuration):
        factory_calls.append(configuration.type)
        if phase == "initialization" and len(factory_calls) == 1:
            demo.clock.elapsed += 40
            raise DisplayBackendInitializationError("temporary initialization failure")
        return Backend()

    class ControlledRetryCoordinator(DisplayPublicationCoordinator):
        def __init__(self, *args, **kwargs):
            coordinators.append(self)
            super().__init__(*args, **kwargs)

        def _wait_before_retry(self, delay):
            delays.append(delay)
            demo.clock.elapsed += delay
            return True

    monkeypatch.setattr(application, "DisplayPublicationCoordinator", ControlledRetryCoordinator)
    demo.run(5, backend_factory=factory)
    assert delays == [1]
    assert updates == ([(1, 0), (1, 0), (1, 1), (1, 2)] if phase == "update" else [(1, 0), (1, 1), (1, 2)])
    assert demo.clock.waits == [5, 5, 5]
    assert successful_update_times == [41, 46, 51]
    assert len(demo.selected) == 1 and len(demo.prepared) == 1
    assert closed == [True]
    assert all(not path.exists() for path in demo.sessions)


def test_keyboard_interrupt_releases_committed_session(demo):
    demo.entry()

    def interrupt(timeout):
        raise KeyboardInterrupt

    demo.clock.on_wait = interrupt
    with pytest.raises(KeyboardInterrupt):
        demo.run()
    assert [identity for identity, *_ in demo.publications] == [(1, 0)]
    demo.assert_clean()
