import netiface


def test_ip_addr_output_picks_robot_interface():
    output = """1: lo    inet 127.0.0.1/8 scope host lo
2: enp3s0    inet 192.168.1.20/24 brd 192.168.1.255 scope global enp3s0
3: eth0    inet 192.168.123.18/24 brd 192.168.123.255 scope global eth0
"""
    assert netiface.parse_ip_addr_output(output) == "eth0"


def test_ifconfig_output_handles_macos_style():
    output = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en8: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.168.123.100 netmask 0xffffff00 broadcast 192.168.123.255
"""
    assert netiface.parse_ifconfig_output(output) == "en8"


def test_ifconfig_output_handles_legacy_addr_prefix():
    output = """eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet addr:192.168.123.18  Bcast:192.168.123.255  Mask:255.255.255.0
"""
    assert netiface.parse_ifconfig_output(output) == "eth0"


def test_no_robot_subnet_returns_none():
    output = """en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 10.0.0.2 netmask 0xffffff00 broadcast 10.0.0.255
"""
    assert netiface.parse_ifconfig_output(output) is None
    assert netiface.parse_ip_addr_output("1: lo inet 127.0.0.1/8") is None


def test_explicit_go2_iface_wins(monkeypatch):
    monkeypatch.setenv("GO2_IFACE", "Ethernet")
    monkeypatch.setattr(netiface, "_detect_posix", lambda: "eth0")
    assert netiface.detect_robot_iface() == "Ethernet"


def test_empty_go2_iface_falls_back_to_detection(monkeypatch):
    monkeypatch.setenv("GO2_IFACE", "")
    monkeypatch.setattr(netiface.sys, "platform", "linux")
    monkeypatch.setattr(netiface, "_detect_posix", lambda: "en8")
    assert netiface.detect_robot_iface() == "en8"


def test_detection_failure_returns_none(monkeypatch):
    monkeypatch.delenv("GO2_IFACE", raising=False)
    monkeypatch.setattr(netiface.sys, "platform", "linux")
    monkeypatch.setattr(netiface, "_detect_posix", lambda: None)
    assert netiface.detect_robot_iface() is None
