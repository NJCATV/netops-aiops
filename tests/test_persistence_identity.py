from aiops.agent.persistence import normalized_device_identity


def test_device_identity_is_bounded_for_database_persistence():
    device_ip, device_name = normalized_device_identity(
        {"managed_device_ip": "10.0.0.1," * 200, "managed_device_name": "OLT-" * 100}
    )

    assert device_ip is not None and len(device_ip) == 512
    assert device_name is not None and len(device_name) == 128


def test_sender_fallback_is_not_persisted_as_managed_device_identity():
    device_ip, device_name = normalized_device_identity(
        {"sender": "172.25.1.9", "device_identity_source": "sender_fallback"}
    )

    assert device_ip is None
    assert device_name is None
