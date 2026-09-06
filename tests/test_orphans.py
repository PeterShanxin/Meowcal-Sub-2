from pathlib import Path

from meocosub2.engine.orphans import ProcessEntry, orphans

OURS = Path(r"C:\Users\viewer\AppData\Local\com.meowcal.sub2\engine\runtime\r\llama-server.exe")
OWN_PID = 4242


def engine(pid: int, parent_pid: int, path: Path = OURS) -> ProcessEntry:
    return ProcessEntry(pid=pid, parent_pid=parent_pid, image_path=path)


def other(pid: int, parent_pid: int = 0) -> ProcessEntry:
    return ProcessEntry(pid=pid, parent_pid=parent_pid, image_path=None)


def test_an_engine_whose_parent_is_gone_is_an_orphan() -> None:
    processes = [other(OWN_PID), engine(900, 800)]
    assert orphans(processes, OURS, OWN_PID) == [processes[1]]


def test_an_engine_whose_parent_is_alive_is_left_alone() -> None:
    """The dangerous mistake: a second copy of the app with a working engine."""
    processes = [other(OWN_PID), other(800), engine(900, 800)]
    assert orphans(processes, OURS, OWN_PID) == []


def test_our_own_engine_is_left_alone() -> None:
    processes = [other(OWN_PID), engine(900, OWN_PID)]
    assert orphans(processes, OURS, OWN_PID) == []


def test_an_engine_from_another_install_is_not_ours_to_end() -> None:
    """Killing by image name is out of scope, however the stranger got there."""
    elsewhere = engine(900, 0, Path(r"D:\tools\llama.cpp\llama-server.exe"))
    assert orphans([other(OWN_PID), elsewhere], OURS, OWN_PID) == []


def test_a_reported_parent_of_zero_means_no_parent_rather_than_the_idle_process() -> None:
    processes = [other(0), other(OWN_PID), engine(900, 0)]
    assert orphans(processes, OURS, OWN_PID) == [processes[2]]


def test_path_spelling_does_not_decide_ownership() -> None:
    verbose = engine(900, 0, Path("\\\\?\\" + str(OURS).upper()))
    assert len(orphans([other(OWN_PID), verbose], OURS, OWN_PID)) == 1


def test_every_stranded_engine_is_collected_not_only_the_first() -> None:
    processes = [other(OWN_PID), engine(900, 800), engine(901, 801)]
    assert len(orphans(processes, OURS, OWN_PID)) == 2
