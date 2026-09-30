from scripts.check_key_management_architecture import violations


def test_key_management_architecture_has_no_active_cloud_or_boundary_violations():
    assert violations() == []
