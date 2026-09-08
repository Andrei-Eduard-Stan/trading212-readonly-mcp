from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VARS_FILE = ROOT / "deploy" / "ansible" / "group_vars" / "all.yml"
TASKS_FILE = (
    ROOT
    / "deploy"
    / "ansible"
    / "roles"
    / "portfolio_mcp"
    / "tasks"
    / "main.yml"
)


def test_deployment_foundation_variables_match_contract():
    text = VARS_FILE.read_text(encoding="utf-8")

    required = {
        "portfolio_service_user: portfolio",
        "portfolio_service_group: portfolio",
        "portfolio_app_dir: /opt/portfolio-hub",
        "portfolio_config_dir: /etc/portfolio-hub",
        "portfolio_state_dir: /var/lib/portfolio-hub",
        "portfolio_cache_dir: /var/lib/portfolio-hub/cache/trading212",
        'portfolio_python_version: "3.14.4"',
        'portfolio_bind_host: "127.0.0.1"',
        "portfolio_bind_port: 8000",
        'portfolio_supported_ubuntu_release: "26.04"',
    }

    for expected in required:
        assert expected in text


def test_service_account_is_non_login_system_identity():
    text = TASKS_FILE.read_text(encoding="utf-8")

    assert 'name: "{{ portfolio_service_user }}"' in text
    assert 'group: "{{ portfolio_service_group }}"' in text
    assert "system: true" in text
    assert "create_home: false" in text
    assert "shell: /usr/sbin/nologin" in text


def test_production_directory_permissions_are_preserved():
    text = TASKS_FILE.read_text(encoding="utf-8")

    application = '''path: "{{ portfolio_app_dir }}"
    state: directory
    owner: root
    group: "{{ portfolio_service_group }}"
    mode: "0750"'''

    configuration = '''path: "{{ portfolio_config_dir }}"
    state: directory
    owner: root
    group: "{{ portfolio_service_group }}"
    mode: "0750"'''

    state = '''path: "{{ portfolio_state_dir }}"
    state: directory
    owner: "{{ portfolio_service_user }}"
    group: "{{ portfolio_service_group }}"
    mode: "0750"'''

    cache = '''path: "{{ portfolio_cache_dir }}"
    state: directory
    owner: "{{ portfolio_service_user }}"
    group: "{{ portfolio_service_group }}"
    mode: "0750"'''

    assert application in text
    assert configuration in text
    assert state in text
    assert cache in text
