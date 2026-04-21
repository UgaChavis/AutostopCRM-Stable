import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DeployScriptTests(unittest.TestCase):
    def test_deploy_script_syncs_active_v1_branch_by_default(self) -> None:
        script = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

        self.assertIn('DEPLOY_BRANCH="${AUTOSTOP_DEPLOY_BRANCH:-autostopcrm-v1}"', script)
        self.assertIn('git fetch "$DEPLOY_REMOTE" "$DEPLOY_BRANCH"', script)
        self.assertIn("git reset --hard FETCH_HEAD", script)

    def test_deploy_script_does_not_sync_legacy_branch(self) -> None:
        script = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

        self.assertNotIn("git fetch origin autostopCRM", script)
        self.assertNotIn("git reset --hard origin/autostopCRM", script)


if __name__ == "__main__":
    unittest.main()
