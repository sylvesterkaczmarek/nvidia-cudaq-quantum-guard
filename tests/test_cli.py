from pathlib import Path

from cudaq_guard.cli import main


def test_policy_check_works_without_cudaq(tmp_path: Path, capsys) -> None:
    policy = tmp_path / "policy.toml"
    policy.write_text(
        '\n'.join([
            'version = 1',
            'name = "test"',
            'allowed_operations = ["sample"]',
            'allowed_targets = ["qpp-cpu"]',
            'allow_remote = false',
            'allow_async = false',
            'max_qubits = 5',
            'max_shots = 2000',
            'allowed_qpu_ids = [0]',
            'require_seed = true',
        ]) + '\n',
        encoding="utf-8",
    )
    rc = main([
        "policy", "check", "--policy", str(policy), "--operation", "sample",
        "--target", "qpp-cpu", "--qubits", "4", "--shots", "1000", "--seed", "7"
    ])
    assert rc == 0
    assert '"allowed": true' in capsys.readouterr().out
