import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_all_workflow_actions_are_pinned_to_full_commits_with_version_comments():
    workflows = list((ROOT / ".github/workflows").glob("*.yml"))
    assert workflows
    count = 0
    for workflow in workflows:
        for line in workflow.read_text().splitlines():
            if re.search(r"\buses:", line):
                assert re.search(r"uses:\s+[\w./-]+@[0-9a-f]{40}\s+#\s+v\d+\.\d+\.\d+\s*$", line), workflow.name
                count += 1
    assert count > 0


def test_dependabot_checks_all_ecosystems_weekly_and_groups_minor_patch():
    config = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    assert config["version"] == 2
    assert {(entry["package-ecosystem"], entry["directory"]) for entry in config["updates"]} == {
        ("github-actions", "/"), ("pip", "/backend"), ("npm", "/frontend"),
    }
    for entry in config["updates"]:
        assert entry["schedule"]["interval"] == "weekly"
        assert any(set(group.get("update-types", [])) == {"minor", "patch"} for group in entry["groups"].values())
