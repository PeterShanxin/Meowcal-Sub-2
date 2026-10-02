"""Read-only WASAPI session state and peak meters, with bounded enumeration.

    https://learn.microsoft.com/windows/win32/coreaudio/audio-sessions
No capture client, loopback buffer or audio recording is created. Each query
owns its COM apartment/interfaces on the calling worker and releases them.
"""

from __future__ import annotations

import ctypes
import os
import uuid
from contextlib import ExitStack

from meocosub2.audio_observation import AudioSession

MAX_DEVICES = 16
MAX_SESSIONS = 64
DEVICE_ENUMERATOR_CLASS = "bcde0395-e52f-467c-8e3d-c4579291692e"
DEVICE_ENUMERATOR = "a95664d2-9614-4f35-a746-de8db63617e6"
SESSION_MANAGER = "77aa99a0-1bd6-484f-8bc7-2c654c9a9b6f"
SESSION_CONTROL = "bfb7ff88-7239-4fc9-8fa2-07c950be9c6d"
PEAK_METER = "c02216f6-8c67-4b5b-9d00-d008e73e0064"


def _guid(value: str) -> ctypes.Array:
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le)


def _call(pointer, index: int, types: tuple, *args) -> int:
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, *types)(table[index])
    return method(pointer, *args)


def _own(stack: ExitStack, pointer: ctypes.c_void_p) -> ctypes.c_void_p:
    if not pointer.value:
        raise OSError("Audio interface unavailable")
    stack.callback(_call, pointer, 2, ())
    return pointer


def _output(stack: ExitStack, pointer, index: int, types: tuple = (), *args):
    result = ctypes.c_void_p()
    if _call(pointer, index, (*types, ctypes.c_void_p), *args, ctypes.byref(result)) < 0:
        raise OSError("Audio enumeration unavailable")
    return _own(stack, result)


def _query(stack: ExitStack, pointer, interface: str):
    return _output(stack, pointer, 0, (ctypes.c_void_p,), ctypes.byref(_guid(interface)))


def _count(pointer, maximum: int) -> int:
    count = ctypes.c_uint()
    if _call(pointer, 3, (ctypes.c_void_p,), ctypes.byref(count)) < 0 or count.value > maximum:
        raise OSError("Audio enumeration limit or query failure")
    return count.value


def _read_session(pointer) -> AudioSession:
    with ExitStack() as stack:
        control = _query(stack, pointer, SESSION_CONTROL)
        process_id, state = ctypes.c_uint(), ctypes.c_int()
        identity_result = _call(control, 14, (ctypes.c_void_p,), ctypes.byref(process_id))
        if identity_result < 0 or _call(control, 3, (ctypes.c_void_p,), ctypes.byref(state)) < 0:
            raise OSError("Audio session disconnected")
        peak: float | None = None
        try:
            meter = _query(stack, control, PEAK_METER)
            value = ctypes.c_float()
            if _call(meter, 3, (ctypes.c_void_p,), ctypes.byref(value)) == 0:
                peak = value.value
        except OSError:
            pass  # Session state remains usable when no peak meter is exposed.
        # AUDCLNT_S_NO_SINGLE_PROCESS is success, but unsuitable attribution.
        return AudioSession(process_id.value, state.value, peak, identity_result == 0)


def _device_sessions(device) -> list[AudioSession]:
    with ExitStack() as stack:
        manager = _output(
            stack,
            device,
            3,
            (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p),
            ctypes.byref(_guid(SESSION_MANAGER)),
            23,
            None,
        )
        enumerator = _output(stack, manager, 5)
        result = []
        for index in range(_count(enumerator, MAX_SESSIONS)):
            with ExitStack() as session_stack:
                session = _output(session_stack, enumerator, 4, (ctypes.c_int,), index)
                result.append(_read_session(session))
        return result


def read_audio_sessions() -> list[AudioSession] | None:
    """Unavailable/device changes remain unknown, never an inferred pause."""
    if os.name != "nt":
        return None
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    ole.CoInitializeEx.restype = ctypes.c_int32
    if ole.CoInitializeEx(None, 0) < 0:
        return None
    try:
        with ExitStack() as stack:
            enumerator = ctypes.c_void_p()
            ole.CoCreateInstance.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            ole.CoCreateInstance.restype = ctypes.c_int32
            if (
                ole.CoCreateInstance(
                    ctypes.byref(_guid(DEVICE_ENUMERATOR_CLASS)),
                    None,
                    1,
                    ctypes.byref(_guid(DEVICE_ENUMERATOR)),
                    ctypes.byref(enumerator),
                )
                < 0
            ):
                return None
            _own(stack, enumerator)
            devices = _output(stack, enumerator, 3, (ctypes.c_int, ctypes.c_uint), 0, 1)
            sessions = []
            for index in range(_count(devices, MAX_DEVICES)):
                with ExitStack() as device_stack:
                    device = _output(device_stack, devices, 4, (ctypes.c_uint,), index)
                    sessions.extend(_device_sessions(device))
            return sessions
    except (OSError, ValueError):
        return None
    finally:
        ole.CoUninitialize()
