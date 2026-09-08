from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VARS = ROOT / "deploy" / "ansible" / "group_vars" / "all.yml"
TASKS = (
    ROOT
    / "deploy"
    / "ansible"
    / "roles"
    / "portfolio_mcp"
    / "tasks"
    / "main.yml"
)


def test_secret_paths_are_external_to_application_tree():
    text = VARS.read_text(encoding="utf-8")

    assert (
        "portfolio_api_key_file: "
        "/etc/portfolio-hub/trading212_api_key"
    ) in text
    assert (
        "portfolio_api_secret_file: "
        "/etc/portfolio-hub/trading212_api_secret"
    ) in text

    assert "portfolio_secret_owner: root" in text
    assert "portfolio_secret_group: portfolio" in text
    assert 'portfolio_secret_mode: "0640"' in text


def test_required_secret_set_contains_only_trading212_credentials():
    text = VARS.read_text(encoding="utf-8")

    assert "portfolio_required_secret_files:" in text
    assert '  - "{{ portfolio_api_key_file }}"' in text
    assert '  - "{{ portfolio_api_secret_file }}"' in text


def test_secret_gate_requires_regular_nonempty_nonsymlink_files():
    text = TASKS.read_text(encoding="utf-8")

    assert "- name: Inspect required Trading 212 credential files" in text
    assert "follow: false" in text

    assert "item.stat.exists" in text
    assert "item.stat.isreg" in text
    assert "not item.stat.islnk" in text
    assert "item.stat.size | int > 0" in text


def test_secret_gate_enforces_owner_group_and_mode():
    text = TASKS.read_text(encoding="utf-8")

    assert "item.stat.pw_name == portfolio_secret_owner" in text
    assert "item.stat.gr_name == portfolio_secret_group" in text
    assert "item.stat.mode == portfolio_secret_mode" in text

    assert text.count("no_log: true") >= 2


def test_service_start_or_restart_occurs_only_after_secret_gate():
    text = TASKS.read_text(encoding="utf-8")

    gate = text.index(
        "- name: Verify required Trading 212 credential file contract"
    )
    decision = text.index(
        "- name: Determine whether controlled service restart is required"
    )
    startup = text.index(
        "- name: Enable and start or restart Portfolio MCP after credential gate"
    )

    assert gate < decision < startup

    startup_section = text[startup:]

    assert 'name: "{{ portfolio_service_name }}"' in startup_section
    assert "enabled: true" in startup_section
    assert "portfolio_service_restart_required" in startup_section
    assert "'restarted'" in startup_section
    assert "'started'" in startup_section


def test_deployment_does_not_embed_broker_auth_values():
    text = TASKS.read_text(encoding="utf-8")

    recovery_section = text[
        text.index("- name: Inspect optional broker auth recovery directory") :
    ]

    assert "content:" not in recovery_section
    assert "lookup(" not in recovery_section
    assert "remote_src: true" in recovery_section
    assert "no_log: true" in recovery_section


def test_restart_decision_consumes_runtime_change_signals():
    text = TASKS.read_text(encoding="utf-8")

    start = text.index(
        "- name: Determine whether controlled service restart is required"
    )
    end = text.index(
        "- name: Enable and start or restart Portfolio MCP after credential gate"
    )

    decision = text[start:end]

    required_signals = (
        "portfolio_venv_create.changed",
        "portfolio_dependency_sync.changed",
        "portfolio_application_copy.changed",
        "portfolio_service_unit_copy.changed",
    )

    for signal in required_signals:
        assert signal in decision
