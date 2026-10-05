from scripts.check_local_executor_architecture import violations


def test_local_executor_architecture_has_no_trust_boundary_violations():
    assert violations() == []
