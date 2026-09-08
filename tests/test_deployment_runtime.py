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


def test_runtime_versions_and_paths_are_pinned():
    text = VARS.read_text(encoding="utf-8")

    required = {
        'portfolio_uv_version: "0.12.9"',
        "portfolio_uv_bin: /usr/local/bin/uv",
        'portfolio_python_version: "3.14.4"',
        "portfolio_python_install_dir: /opt/portfolio-hub/python",
        "portfolio_venv_dir: /opt/portfolio-hub/venv",
        "portfolio_runtime_lock: /opt/portfolio-hub/requirements.lock.txt",
    }

    for value in required:
        assert value in text


def test_uv_is_installed_as_system_unmanaged_runtime():
    text = TASKS.read_text(encoding="utf-8")

    assert "https://astral.sh/uv/{{ portfolio_uv_version }}/install.sh" in text
    assert "UV_UNMANAGED_INSTALL: /usr/local/bin" in text


def test_python_installation_is_not_root_home_dependent():
    text = TASKS.read_text(encoding="utf-8")

    assert "--install-dir" in text
    assert '"{{ portfolio_python_install_dir }}"' in text
    assert "--no-bin" in text

    assert "/root/.local" not in text
    assert "/root/.cache" not in text


def test_exact_production_lock_is_deployed_and_verified():
    text = TASKS.read_text(encoding="utf-8")

    assert "../../requirements.lock.txt" in text
    assert '"{{ portfolio_runtime_lock }}"' in text
    assert "pip" in text
    assert "sync" in text
    assert "pip freeze" in text
    assert "diff -u" in text


def test_dependency_sync_is_conditionally_idempotent():
    text = TASKS.read_text(encoding="utf-8")

    assert "register: portfolio_dependency_check" in text
    assert "failed_when: portfolio_dependency_check.rc not in [0, 1]" in text
    assert "when: portfolio_dependency_check.rc == 1" in text

    sync_section = text.split(
        "- name: Synchronize exact production dependency environment",
        1,
    )[1].split(
        "- name: Verify virtual environment Python version",
        1,
    )[0]

    assert "changed_when: false" not in sync_section
