from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy" / "ansible" / "site.yml"
VARS = ROOT / "deploy" / "ansible" / "group_vars" / "all.yml"
TASKS = (
    ROOT
    / "deploy"
    / "ansible"
    / "roles"
    / "portfolio_network"
    / "tasks"
    / "main.yml"
)


def test_network_role_runs_after_application_role():
    text = SITE.read_text(encoding="utf-8")

    assert "- portfolio_mcp" in text
    assert "- portfolio_network" in text
    assert text.index("- portfolio_mcp") < text.index("- portfolio_network")


def test_network_contract_uses_verified_identity_not_static_ip():
    text = VARS.read_text(encoding="utf-8")

    assert "portfolio_tailscale_expected_hostname: portfolio-hub" in text
    assert (
        "portfolio_tailscale_expected_dns_name: "
        "portfolio-hub.tail894a11.ts.net."
    ) in text

    assert "100.93.219.125" not in text


def test_network_contract_pins_verified_tailscale_supply_chain():
    text = VARS.read_text(encoding="utf-8")

    assert 'portfolio_tailscale_baseline_version: "1.102.2"' in text
    assert "https://pkgs.tailscale.com/stable/ubuntu/resolute.noarmor.gpg" in text
    assert (
        "3e03dacf222698c60b8e2f990b809ca1b3e104de127767864284e6c228f1fb39"
        in text
    )
    assert "signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg" in text


def test_network_contract_pins_verified_ufw_baseline():
    text = VARS.read_text(encoding="utf-8")

    assert 'portfolio_ufw_baseline_version: "0.36.2-9build1"' in text
    assert "portfolio_tailscale_interface: tailscale0" in text
    assert "portfolio_ssh_port: 22" in text


def test_tailscaled_starts_before_authentication_gate():
    text = TASKS.read_text(encoding="utf-8")

    service = text.index("Ensure tailscaled is enabled and running")
    status = text.index("Inspect Tailscale authentication state")
    identity = text.index("Verify exact Tailscale identity before network exposure")

    assert service < status < identity


def test_tailscale_identity_gate_precedes_firewall_mutation():
    text = TASKS.read_text(encoding="utf-8")

    identity = text.index("Verify exact Tailscale identity before network exposure")
    firewall = text.index("Set UFW default incoming policy")

    assert identity < firewall
    assert "sudo tailscale up --hostname=portfolio-hub" in text
    assert "portfolio-hub.tail894a11.ts.net." in text


def test_tailscale_preferences_preserve_verified_production_behavior():
    text = TASKS.read_text(encoding="utf-8")

    assert "--accept-dns=true" in text
    assert "--auto-update=true" in text
    assert 'portfolio_tailscale_prefs_verified["CorpDNS"]' in text
    assert 'portfolio_tailscale_prefs_verified["AutoUpdate"]["Apply"]' in text


def test_funnel_is_persistent_and_targets_loopback_mcp():
    vars_text = VARS.read_text(encoding="utf-8")
    tasks_text = TASKS.read_text(encoding="utf-8")

    assert 'portfolio_funnel_target: "http://127.0.0.1:8000"' in vars_text
    assert (
        'portfolio_funnel_public_url: '
        '"https://portfolio-hub.tail894a11.ts.net"'
    ) in vars_text

    assert "- --bg" in tasks_text
    assert "- --yes" in tasks_text
    assert "portfolio_funnel_target" in tasks_text


def test_firewall_refuses_unexpected_existing_allow_rules():
    text = TASKS.read_text(encoding="utf-8")

    assert "ufw" in text
    assert "show" in text
    assert "added" in text
    assert "Refuse unexpected pre-existing UFW allow rules" in text
    assert "Refusing to rewrite firewall policy automatically" in text


def test_firewall_reproduces_verified_exposure_contract():
    vars_text = VARS.read_text(encoding="utf-8")
    tasks_text = TASKS.read_text(encoding="utf-8")

    assert (
        'portfolio_ufw_expected_ssh_rule: '
        '"ufw allow in on tailscale0 to any port 22 proto tcp"'
    ) in vars_text

    assert "default" in tasks_text
    assert "deny" in tasks_text
    assert "incoming" in tasks_text
    assert "allow" in tasks_text
    assert "outgoing" in tasks_text
    assert "--force" in tasks_text
    assert "enable" in tasks_text
    assert (
        "Default: deny (incoming), allow (outgoing), disabled (routed)"
        in tasks_text
    )


def test_network_role_verifies_no_public_mcp_listener():
    text = TASKS.read_text(encoding="utf-8")

    assert "127.0.0.1:8000" in text
    assert "0.0.0.0:8000" in text
    assert "[::]:8000" in text
    assert "Require loopback-only MCP listener" in text


def test_network_recovery_contains_no_tailscale_credentials():
    vars_text = VARS.read_text(encoding="utf-8").lower()
    tasks_text = TASKS.read_text(encoding="utf-8").lower()

    combined = vars_text + tasks_text

    assert "--auth-key" not in combined
    assert "ts_authkey" not in combined
    assert "oauth_client_secret" not in combined
    assert "100.93.219.125" not in combined


def test_package_baselines_never_downgrade_auto_updated_network_software():
    vars_text = VARS.read_text(encoding="utf-8")
    tasks_text = TASKS.read_text(encoding="utf-8")

    assert 'portfolio_tailscale_baseline_version: "1.102.2"' in vars_text
    assert 'portfolio_ufw_baseline_version: "0.36.2-9build1"' in vars_text

    assert "portfolio_tailscale_baseline_check" in tasks_text
    assert "portfolio_ufw_baseline_check" in tasks_text

    assert "allow_downgrade: true" not in tasks_text
    assert "allow_downgrade: false" in tasks_text

    assert (
        'name: "tailscale={{ portfolio_tailscale_baseline_version }}"'
        in tasks_text
    )
    assert (
        'name: "ufw={{ portfolio_ufw_baseline_version }}"'
        in tasks_text
    )
