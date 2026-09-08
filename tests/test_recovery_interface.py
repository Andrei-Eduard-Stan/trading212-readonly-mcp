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


def test_recovery_interface_is_disabled_by_default():
    text = VARS.read_text(encoding="utf-8")

    assert 'portfolio_recovery_auth_dir: ""' in text


def test_recovery_interface_maps_only_required_broker_auth_files():
    text = VARS.read_text(encoding="utf-8")

    assert "portfolio_recovery_auth_files:" in text
    assert "source_name: trading212_api_key" in text
    assert 'destination: "{{ portfolio_api_key_file }}"' in text
    assert "source_name: trading212_api_secret" in text
    assert 'destination: "{{ portfolio_api_secret_file }}"' in text


def test_recovery_directory_must_be_absolute_directory_and_not_symlink():
    text = TASKS.read_text(encoding="utf-8")

    assert "portfolio_recovery_auth_dir is match('^/')" in text
    assert "portfolio_recovery_auth_dir_stat.stat.exists" in text
    assert "portfolio_recovery_auth_dir_stat.stat.isdir" in text
    assert "not portfolio_recovery_auth_dir_stat.stat.islnk" in text


def test_recovery_files_must_be_regular_nonsymlink_and_nonempty():
    text = TASKS.read_text(encoding="utf-8")

    assert "item.stat.exists" in text
    assert "item.stat.isreg" in text
    assert "not item.stat.islnk" in text
    assert "item.stat.size | int > 0" in text


def test_recovery_copy_uses_external_files_and_protected_target_mode():
    text = TASKS.read_text(encoding="utf-8")

    assert "- name: Restore broker auth files into protected configuration" in text
    assert "remote_src: true" in text
    assert 'owner: "{{ portfolio_secret_owner }}"' in text
    assert 'group: "{{ portfolio_secret_group }}"' in text
    assert 'mode: "{{ portfolio_secret_mode }}"' in text
    assert "register: portfolio_recovery_auth_copy" in text
    assert "no_log: true" in text


def test_auth_recovery_change_participates_in_restart_decision():
    text = TASKS.read_text(encoding="utf-8")

    start = text.index(
        "- name: Determine whether controlled service restart is required"
    )
    end = text.index(
        "- name: Enable and start or restart Portfolio MCP after credential gate"
    )

    decision = text[start:end]

    assert "portfolio_recovery_auth_copy.changed" in decision
