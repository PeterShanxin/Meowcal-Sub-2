import ctypes
import os
from unittest.mock import MagicMock

import pytest

import meocosub2.windows_audio as audio
from meocosub2.audio_observation import AudioSession

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows COM ABI")


def output(pointer, value):
    ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0] = value


class Interface:
    """In-memory COM boundary with real native vtables and owned references."""

    def __init__(self):
        self.table = (ctypes.c_void_p * 17)()
        self.object = ctypes.pointer(ctypes.cast(self.table, ctypes.POINTER(ctypes.c_void_p)))
        self.pointer = ctypes.cast(self.object, ctypes.c_void_p)
        self.callbacks = []
        self.releases = 0
        self.method(2, (), self.release)

    def release(self):
        self.releases += 1
        return 0

    def method(self, index, types, body):
        callback = ctypes.WINFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, *types)(
            lambda _, *args: body(*args)
        )
        self.callbacks.append(callback)
        self.table[index] = ctypes.cast(callback, ctypes.c_void_p)

    def returns(self, index, types, target):
        def call(*args):
            output(args[-1], target.pointer)
            return 0

        self.method(index, (*types, ctypes.c_void_p), call)

    def count(self, value):
        def count(pointer):
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint))[0] = value
            return 0

        self.method(3, (ctypes.c_void_p,), count)


class AudioSystem:
    def __init__(self, *, identity_result=0, state=1, meter=True, failed_state=False, sessions=1):
        (
            self.enumerator,
            self.collection,
            self.device,
            self.manager,
            self.sessions,
            self.control,
            self.meter,
        ) = [Interface() for _ in range(7)]
        self.ole = MagicMock()
        self.ole.CoInitializeEx.return_value = 0

        def create(_class, _outer, _context, _interface, result):
            output(result, self.enumerator.pointer)
            return 0

        self.ole.CoCreateInstance.side_effect = create
        self.enumerator.returns(3, (ctypes.c_int, ctypes.c_uint), self.collection)
        self.collection.count(1)
        self.collection.returns(4, (ctypes.c_uint,), self.device)
        self.device.returns(3, (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p), self.manager)
        self.manager.returns(5, (), self.sessions)
        self.sessions.count(sessions)
        self.sessions.returns(4, (ctypes.c_int,), self.control)

        def query(guid, result):
            requested = bytes(ctypes.string_at(guid, 16))
            if requested == bytes(audio._guid(audio.SESSION_CONTROL)):
                output(result, self.control.pointer)
                return 0
            if requested == bytes(audio._guid(audio.PEAK_METER)) and meter:
                output(result, self.meter.pointer)
                return 0
            return -2147467262

        self.control.method(0, (ctypes.c_void_p, ctypes.c_void_p), query)

        def process_id(result):
            ctypes.cast(result, ctypes.POINTER(ctypes.c_uint))[0] = 42
            return identity_result

        self.control.method(14, (ctypes.c_void_p,), process_id)

        def get_state(result):
            ctypes.cast(result, ctypes.POINTER(ctypes.c_int))[0] = state
            return -1 if failed_state else 0

        self.control.method(3, (ctypes.c_void_p,), get_state)

        def peak(result):
            ctypes.cast(result, ctypes.POINTER(ctypes.c_float))[0] = 0.5
            return 0

        self.meter.method(3, (ctypes.c_void_p,), peak)

    def install(self, monkeypatch):
        monkeypatch.setattr(audio.ctypes, "WinDLL", lambda _: self.ole)

    def assert_released(self, *, session=True, meter=True):
        for interface in (
            self.enumerator,
            self.collection,
            self.device,
            self.manager,
            self.sessions,
        ):
            assert interface.releases == 1
        assert self.control.releases == (2 if session else 0)
        assert self.meter.releases == int(meter and session)
        self.ole.CoUninitialize.assert_called_once()


@pytest.mark.parametrize("state", [0, 1, 2])
def test_real_com_boundary_reads_player_identity_state_and_peak_and_releases(monkeypatch, state):
    system = AudioSystem(state=state)
    system.install(monkeypatch)
    assert audio.read_audio_sessions() == [AudioSession(42, state, 0.5)]
    system.assert_released()


def test_unavailable_peak_meter_does_not_fabricate_silence_or_discard_state(monkeypatch):
    system = AudioSystem(meter=False)
    system.install(monkeypatch)
    assert audio.read_audio_sessions() == [AudioSession(42, 1, None)]
    system.assert_released(meter=False)


def test_multi_process_success_is_preserved_as_ambiguous_attribution(monkeypatch):
    system = AudioSystem(identity_result=1)
    system.install(monkeypatch)
    assert audio.read_audio_sessions() == [AudioSession(42, 1, 0.5, False)]
    system.assert_released()


def test_disconnected_session_returns_unknown_and_releases_all_interfaces(monkeypatch):
    system = AudioSystem(failed_state=True)
    system.install(monkeypatch)
    assert audio.read_audio_sessions() is None
    system.assert_released(meter=False)


def test_enumeration_limit_returns_unknown_without_leaking_interfaces(monkeypatch):
    system = AudioSystem(sessions=audio.MAX_SESSIONS + 1)
    system.install(monkeypatch)
    assert audio.read_audio_sessions() is None
    system.assert_released(session=False, meter=False)


def test_apartment_or_activation_failure_remains_unknown(monkeypatch):
    system = AudioSystem()
    system.install(monkeypatch)
    system.ole.CoInitializeEx.return_value = -1
    assert audio.read_audio_sessions() is None
    system.ole.CoUninitialize.assert_not_called()
    system.ole.CoInitializeEx.return_value = 0
    system.ole.CoCreateInstance.side_effect = None
    system.ole.CoCreateInstance.return_value = -1
    assert audio.read_audio_sessions() is None
    system.ole.CoUninitialize.assert_called_once()
