import subprocess
from pathlib import Path


class WorktreeManager:
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.worktrees_dir = self.project_path / ".worktrees"

    def create(self, task_id: str, branch_name: str) -> Path:
        """Create an isolated worktree for a task"""
        self.worktrees_dir.mkdir(exist_ok=True)
        worktree_path = self.worktrees_dir / task_id

        if worktree_path.exists():
            raise ValueError(f"Worktree already exists for task {task_id}")

        try:
            # Create worktree from develop branch
            subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(worktree_path), "develop"],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True
            )
            return worktree_path
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create worktree: {e.stderr}")

    def remove(self, task_id: str):
        """Remove a worktree"""
        worktree_path = self.worktrees_dir / task_id

        if not worktree_path.exists():
            return

        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path), "--force"],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to remove worktree: {e.stderr}")

    def list_worktrees(self) -> list[dict]:
        """List all worktrees"""
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True
            )
            return self._parse_worktree_list(result.stdout)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to list worktrees: {e.stderr}")

    def _parse_worktree_list(self, output: str) -> list[dict]:
        """Parse git worktree list output"""
        worktrees = []
        current = {}

        for line in output.strip().split('\n'):
            if line.startswith('worktree '):
                if current:
                    worktrees.append(current)
                current = {'path': line.split(' ', 1)[1]}
            elif line.startswith('branch '):
                current['branch'] = line.split(' ', 1)[1]

        if current:
            worktrees.append(current)

        return worktrees

    def merge_to_main(self, branch_name: str, target_branch: str = "main"):
        """Merge a worktree branch into the target branch"""
        try:
            subprocess.run(
                ["git", "checkout", target_branch],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True
            )

            subprocess.run(
                ["git", "merge", "--no-ff", branch_name, "-m", f"Merge {branch_name} into {target_branch}"],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to merge branch: {e.stderr}")
