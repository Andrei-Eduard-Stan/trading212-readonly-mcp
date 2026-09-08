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


def test_application_deployment_uses_explicit_allowlist():
    text = VARS.read_text(encoding="utf-8")

    required = {
        "  - server.py",
        "  - trading212.py",
        "  - portfolio_accounting.py",
        "  - portfolio_snapshot_service.py",
        "  - requirements.txt",
    }

    for value in required:
        assert value in text

    assert "portfolio_application_files:" in text


def test_application_files_are_deployed_with_restricted_permissions():
    text = TASKS.read_text(encoding="utf-8")

    assert 'src: "{{ playbook_dir }}/../../src/{{ item }}"' in text
    assert 'dest: "{{ portfolio_app_dir }}/{{ item }}"' in text
    assert "owner: root" in text
    assert 'group: "{{ portfolio_service_group }}"' in text
    assert 'mode: "0640"' in text
    assert 'loop: "{{ portfolio_application_files }}"' in text


def test_application_deployment_has_read_back_verification():
    text = TASKS.read_text(encoding="utf-8")

    assert "- name: Verify deployed application files byte-for-byte" in text
    assert "      - cmp" in text
    assert "      - -s" in text
    assert '      - "{{ playbook_dir }}/../../src/{{ item }}"' in text
    assert '      - "{{ portfolio_app_dir }}/{{ item }}"' in text


def test_deployed_source_is_validated_without_writing_bytecode():
    text = TASKS.read_text(encoding="utf-8")

    assert (
        "- name: Syntax-check deployed application modules without writing bytecode"
        in text
    )
    assert "compile(Path(path).read_text" in text
    assert "py_compile" not in text

    assert '"{{ portfolio_app_dir }}/server.py"' in text
    assert '"{{ portfolio_app_dir }}/trading212.py"' in text
    assert '"{{ portfolio_app_dir }}/portfolio_accounting.py"' in text
    assert '"{{ portfolio_app_dir }}/portfolio_snapshot_service.py"' in text

    assert "- name: Import credential-independent deployed modules" in text
    assert "import portfolio_accounting" in text
    assert "import portfolio_snapshot_service" in text
    assert 'PYTHONDONTWRITEBYTECODE: "1"' in text


def test_systemd_unit_is_deployed_but_service_is_not_started():
    text = TASKS.read_text(encoding="utf-8")

    assert 'src: "{{ playbook_dir }}/../portfolio-mcp.service"' in text
    assert 'dest: "{{ portfolio_service_unit }}"' in text
    assert 'mode: "0644"' in text
    assert "register: portfolio_service_unit_copy" in text
    assert "daemon_reload: true" in text
    assert "when: portfolio_service_unit_copy.changed" in text

    forbidden = (
        "state: started",
        "state: restarted",
        "enabled: true",
        "systemctl start",
        "systemctl restart",
    )

    for value in forbidden:
        assert value not in text
