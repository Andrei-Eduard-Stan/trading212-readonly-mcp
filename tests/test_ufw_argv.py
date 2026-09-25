from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NETWORK_TASKS = (
    ROOT
    / "deploy"
    / "ansible"
    / "roles"
    / "portfolio_network"
    / "tasks"
    / "main.yml"
)


def test_ufw_interface_token_on_is_quoted_as_literal_string():
    text = NETWORK_TASKS.read_text(encoding="utf-8")

    marker = "- name: Allow SSH only through Tailscale interface"
    start = text.index(marker)
    block = text[start:start + 700]

    assert '      - "on"\n' in block
    assert '      - on\n' not in block
