from scripts.check_topstep_onboarding_architecture import scan_text, violations


def test_repository_topstep_onboarding_architecture_passes():
    assert violations() == []


def test_guard_rejects_order_endpoint_and_process_local_approval():
    found = scan_text("app/bad.py", 'url = "/api/Order/place"\napprovedAccountId = "123"')
    assert len(found) == 2


def test_guard_rejects_secret_logging_and_name_authorization():
    found = scan_text("app/bad.py", 'logger.info(api_key)\napproved = account.name == "Combine"')
    assert any("secret logging" in item for item in found)
    assert any("account-name" in item for item in found)


def test_guard_allows_encrypted_credential_access_only_in_service():
    assert scan_text("app/topstep_onboarding.py", "TopstepCredential.api_key_encrypted") == []
    assert any("credential read" in item for item in
               scan_text("app/worker.py", "TopstepCredential.api_key_encrypted"))


def test_guard_rejects_process_local_session_and_unapproved_session_access():
    assert any("in-memory" in item for item in
               scan_text("app/worker.py", "_session_token_cache = token"))
    assert any("session access" in item for item in
               scan_text("app/worker.py", "TopstepProviderSession.state == 'valid'"))
    assert scan_text("app/topstep_session_security.py", "TopstepProviderSession.state") == []
