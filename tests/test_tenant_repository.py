from dataclasses import replace

import pytest

from app.authorization import TenantContext
from app.tenant_repository import TenantScopeError, VerifiedTenantJob, require_tenant


def test_missing_and_invalid_tenant_fail_closed():
    for value in (None, TenantContext(0, "bad"), object()):
        with pytest.raises(TenantScopeError, match="validated_tenant_required"):
            require_tenant(value)


def test_job_envelope_rejects_forged_tenant_and_command():
    job = VerifiedTenantJob.issue(TenantContext(7, "alice"), "command-1", "shared-job-key")
    assert job.validate("shared-job-key", expected_tenant=7, expected_command="command-1").user_id == 7
    with pytest.raises(TenantScopeError, match="invalid_job_tenant"):
        job.validate("shared-job-key", expected_tenant=8, expected_command="command-1")
    with pytest.raises(TenantScopeError, match="invalid_job_tenant"):
        replace(job, signature="0" * 64).validate(
            "shared-job-key", expected_tenant=7, expected_command="command-1"
        )
