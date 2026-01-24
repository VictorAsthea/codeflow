"""
Roadmap storage service for .codeflow/roadmap.json

This module provides CRUD operations for roadmap data with atomic file operations.
"""

import json
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Any

from backend.models import (
    Roadmap,
    Feature,
    FeatureStatus,
    ProjectAnalysis,
    CompetitorAnalysis,
)


class RoadmapStorage:
    """
    Storage service for roadmap data.

    Stores roadmap in .codeflow/roadmap.json with atomic writes.
    """

    def __init__(self, base_path: Path | None = None):
        """
        Initialize roadmap storage.

        Args:
            base_path: Base directory for .codeflow storage. Defaults to project root.
        """
        if base_path is None:
            base_path = Path.cwd()

        self.base_path = Path(base_path)
        self.codeflow_dir = self.base_path / ".codeflow"
        self.roadmap_file = self.codeflow_dir / "roadmap.json"

        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directories if they don't exist."""
        self.codeflow_dir.mkdir(exist_ok=True)

    def _atomic_write(self, file_path: Path, data: dict):
        """
        Atomically write data to a JSON file.

        Writes to a temporary file first, then renames it to the target path.
        """
        file_path.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_path = tempfile.mkstemp(
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp"
        )

        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)

            temp_path_obj = Path(temp_path)
            temp_path_obj.replace(file_path)
        except Exception:
            try:
                Path(temp_path).unlink()
            except FileNotFoundError:
                pass
            raise

    def _read_json(self, file_path: Path) -> dict:
        """Read and parse a JSON file."""
        if not file_path.exists():
            return {}

        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _parse_datetime(self, data: dict, field: str):
        """Parse datetime string to datetime object if it's a string."""
        if isinstance(data.get(field), str):
            data[field] = datetime.fromisoformat(data[field])

    def has_roadmap(self) -> bool:
        """Check if a roadmap exists."""
        return self.roadmap_file.exists()

    def get_roadmap(self) -> Roadmap | None:
        """
        Load roadmap from storage.

        Returns:
            Roadmap object or None if not found
        """
        if not self.roadmap_file.exists():
            return None

        data = self._read_json(self.roadmap_file)
        roadmap_data = data.get("roadmap", {})

        # Parse feature dates
        for feature in roadmap_data.get("features", []):
            self._parse_datetime(feature, "created_at")
            self._parse_datetime(feature, "updated_at")

        # Parse analysis date
        if roadmap_data.get("analysis"):
            self._parse_datetime(roadmap_data["analysis"], "date")

        # Parse competitor analysis date
        if roadmap_data.get("competitor_analysis"):
            self._parse_datetime(roadmap_data["competitor_analysis"], "date")

        return Roadmap(**roadmap_data)

    def save_roadmap(self, roadmap: Roadmap):
        """
        Save roadmap to storage atomically.

        Args:
            roadmap: Roadmap object to save
        """
        data = {
            "roadmap": roadmap.model_dump(mode="json"),
            "version": "1.0",
            "last_updated": datetime.now().isoformat()
        }

        self._atomic_write(self.roadmap_file, data)

    def get_analysis_status(self) -> dict[str, Any]:
        """
        Check if project and competitor analysis exist.

        Returns:
            Dictionary with analysis status information
        """
        roadmap = self.get_roadmap()

        if not roadmap:
            return {
                "has_roadmap": False,
                "has_project_analysis": False,
                "has_competitor_analysis": False,
                "has_features": False,
                "features_count": 0
            }

        return {
            "has_roadmap": True,
            "has_project_analysis": roadmap.analysis is not None,
            "has_competitor_analysis": roadmap.competitor_analysis is not None,
            "has_features": len(roadmap.features) > 0,
            "features_count": len(roadmap.features),
            "project_name": roadmap.project_name,
            "project_analysis_date": roadmap.analysis.date.isoformat() if roadmap.analysis else None,
            "competitor_analysis_date": roadmap.competitor_analysis.date.isoformat() if roadmap.competitor_analysis else None
        }

    def add_feature(self, feature: Feature) -> Feature:
        """
        Add a new feature to the roadmap.

        Args:
            feature: Feature object to add

        Returns:
            Added feature
        """
        roadmap = self.get_roadmap()
        if not roadmap:
            roadmap = Roadmap()

        roadmap.features.append(feature)
        self.save_roadmap(roadmap)
        return feature

    def update_feature(self, feature_id: str, updates: dict) -> Feature | None:
        """
        Update an existing feature.

        Args:
            feature_id: Feature ID to update
            updates: Dictionary of fields to update

        Returns:
            Updated feature or None if not found
        """
        roadmap = self.get_roadmap()
        if not roadmap:
            return None

        for i, feature in enumerate(roadmap.features):
            if feature.id == feature_id:
                feature_dict = feature.model_dump()
                for key, value in updates.items():
                    if value is not None:
                        feature_dict[key] = value
                feature_dict["updated_at"] = datetime.now()
                roadmap.features[i] = Feature(**feature_dict)
                self.save_roadmap(roadmap)
                return roadmap.features[i]

        return None

    def delete_feature(self, feature_id: str) -> bool:
        """
        Delete a feature from the roadmap.

        Args:
            feature_id: Feature ID to delete

        Returns:
            True if deleted, False if not found
        """
        roadmap = self.get_roadmap()
        if not roadmap:
            return False

        original_count = len(roadmap.features)
        roadmap.features = [f for f in roadmap.features if f.id != feature_id]

        if len(roadmap.features) < original_count:
            self.save_roadmap(roadmap)
            return True

        return False

    def get_feature(self, feature_id: str) -> Feature | None:
        """
        Get a single feature by ID.

        Args:
            feature_id: Feature ID

        Returns:
            Feature object or None if not found
        """
        roadmap = self.get_roadmap()
        if not roadmap:
            return None

        for feature in roadmap.features:
            if feature.id == feature_id:
                return feature

        return None

    def update_feature_status(self, feature_id: str, status: FeatureStatus) -> Feature | None:
        """
        Update feature status (for drag-drop).

        Args:
            feature_id: Feature ID
            status: New status

        Returns:
            Updated feature or None if not found
        """
        return self.update_feature(feature_id, {"status": status})

    def set_feature_task_id(self, feature_id: str, task_id: str) -> Feature | None:
        """
        Link a feature to a task.

        Args:
            feature_id: Feature ID
            task_id: Task ID to link

        Returns:
            Updated feature or None if not found
        """
        return self.update_feature(feature_id, {"task_id": task_id})

    def update_project_analysis(self, analysis: ProjectAnalysis):
        """
        Update project analysis data.

        Args:
            analysis: ProjectAnalysis object
        """
        roadmap = self.get_roadmap()
        if not roadmap:
            roadmap = Roadmap()

        roadmap.analysis = analysis
        self.save_roadmap(roadmap)

    def update_competitor_analysis(self, analysis: CompetitorAnalysis):
        """
        Update competitor analysis data.

        Args:
            analysis: CompetitorAnalysis object
        """
        roadmap = self.get_roadmap()
        if not roadmap:
            roadmap = Roadmap()

        roadmap.competitor_analysis = analysis
        self.save_roadmap(roadmap)

    def clear_roadmap(self):
        """Clear all roadmap data."""
        if self.roadmap_file.exists():
            self.roadmap_file.unlink()
