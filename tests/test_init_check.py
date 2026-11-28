"""init_check probes are fully injected — no dependence on the test host."""

from aimerge import init_check


def test_marker_present_is_systemd():
    assert init_check.is_systemd(path_exists=lambda p: True, proc1_comm=lambda: "nope")
    assert init_check.detected_init(path_exists=lambda p: True, proc1_comm=lambda: "nope") == "systemd"


def test_openrc_host_without_marker():
    assert not init_check.is_systemd(path_exists=lambda p: False, proc1_comm=lambda: "openrc:init")
    assert init_check.detected_init(path_exists=lambda p: False, proc1_comm=lambda: "openrc:init") == "openrc:init"


def test_fallback_comm_systemd_without_marker():
    assert init_check.is_systemd(path_exists=lambda p: False, proc1_comm=lambda: "systemd\n")


def test_empty_comm_is_unknown():
    assert init_check.detected_init(path_exists=lambda p: False, proc1_comm=lambda: "") == "unknown"
    assert not init_check.is_systemd(path_exists=lambda p: False, proc1_comm=lambda: "")


def test_exploding_probes_fail_closed_to_unknown():
    def boom_path(p):
        raise OSError("no /run")

    def boom_comm():
        raise PermissionError("/proc hidden")

    assert not init_check.is_systemd(path_exists=boom_path, proc1_comm=lambda: "systemd")
    assert init_check.detected_init(path_exists=boom_path, proc1_comm=boom_comm) == "unknown"
    assert not init_check.is_systemd(path_exists=lambda p: False, proc1_comm=boom_comm)
    assert init_check.detected_init(path_exists=lambda p: False, proc1_comm=boom_comm) == "unknown"
