"""
Roadmap API endpoints.

Provides endpoints for roadmap management, feature CRUD, and AI-powered generation.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
import uuid

from backend.models import (
    Roadmap,
    Feature,
    FeatureCreate,
    FeatureUpdate,
    FeatureStatus,
    RoadmapUpdate,
    Priority,
    RoadmapPhase,
    Complexity,
    Impact,
)
from backend.services.roadmap_storage import RoadmapStorage
from backend.services import roadmap_ai
from backend.config import settings
from backend.validation import FeatureId
from backend.utils.project_helpers import get_active_project_path
from pathlib import Path

router = APIRouter()

# Storage instance
_storage: RoadmapStorage | None = None


def get_storage() -> RoadmapStorage:
    """Get or create storage instance."""
    global _storage
    if _storage is None:
        _storage = RoadmapStorage()
    return _storage


# ============== Roadmap CRUD ==============

@router.get("/roadmap")
async def get_roadmap():
    """Get the full roadmap with all features."""
    storage = get_storage()
    roadmap = storage.get_roadmap()

    if not roadmap:
        return {"roadmap": None}

    return {"roadmap": roadmap.model_dump(mode="json")}


@router.put("/roadmap")
async def update_roadmap(data: RoadmapUpdate):
    """Update roadmap settings (name, description, audience, personas)."""
    storage = get_storage()
    roadmap = storage.get_roadmap()

    if not roadmap:
        roadmap = Roadmap()

    if data.project_name is not None:
        roadmap.project_name = data.project_name
    if data.project_description is not None:
        roadmap.project_description = data.project_description
    if data.target_audience is not None:
        roadmap.target_audience = data.target_audience
    if data.personas is not None:
        roadmap.personas = data.personas

    storage.save_roadmap(roadmap)
    return {"roadmap": roadmap.model_dump(mode="json")}


# ============== Feature CRUD ==============

@router.post("/roadmap/features")
async def create_feature(data: FeatureCreate):
    """Add a new feature to the roadmap."""
    storage = get_storage()

    feature = Feature(
        id=f"feat-{uuid.uuid4().hex[:8]}",
        title=data.title,
        description=data.description,
        justification=data.justification,
        phase=data.phase,
        priority=data.priority,
        complexity=data.complexity,
        impact=data.impact,
        status=FeatureStatus.UNDER_REVIEW,
        created_at=datetime.now(),
        updated_at=datetime.now()
    )

    storage.add_feature(feature)
    return {"feature": feature.model_dump(mode="json")}


@router.patch("/roadmap/features/{feature_id}")
async def update_feature(feature_id: FeatureId, data: FeatureUpdate):
    """Update a feature's properties."""
    storage = get_storage()

    updates = data.model_dump(exclude_unset=True)
    feature = storage.update_feature(feature_id, updates)

    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    return {"feature": feature.model_dump(mode="json")}


@router.delete("/roadmap/features/{feature_id}")
async def delete_feature(feature_id: FeatureId):
    """Delete a feature from the roadmap."""
    storage = get_storage()

    if not storage.delete_feature(feature_id):
        raise HTTPException(status_code=404, detail="Feature not found")

    return {"message": "Feature deleted successfully"}


@router.patch("/roadmap/features/{feature_id}/status")
async def update_feature_status(feature_id: FeatureId, status: FeatureStatus):
    """Update feature status (for drag-drop)."""
    storage = get_storage()

    feature = storage.update_feature_status(feature_id, status)

    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    return {"feature": feature.model_dump(mode="json")}


class StatusUpdateRequest(BaseModel):
    status: FeatureStatus


@router.patch("/roadmap/features/{feature_id}/drag")
async def drag_feature(feature_id: FeatureId, data: StatusUpdateRequest):
    """Update feature status via drag-drop."""
    storage = get_storage()

    feature = storage.update_feature_status(feature_id, data.status)

    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    return {"feature": feature.model_dump(mode="json")}


# ============== Build Feature (Convert to Task) ==============

@router.post("/roadmap/features/{feature_id}/build")
async def build_feature(feature_id: FeatureId):
    """Create a task from a feature."""
    from backend.main import storage as task_storage
    from backend.models import Task, TaskStatus, Phase, PhaseConfig, PhaseStatus

    roadmap_storage = get_storage()
    feature = roadmap_storage.get_feature(feature_id)

    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    if feature.task_id:
        # Already has a task, return existing
        existing_task = task_storage.get_task(feature.task_id)
        if existing_task:
            return {
                "message": "Feature already has a task",
                "task_id": feature.task_id,
                "task": existing_task.model_dump(mode="json")
            }

    # Create task description from feature
    description = f"""## {feature.title}

{feature.description}

### Justification
{feature.justification or 'No justification provided.'}

### Details
- **Phase**: {feature.phase.value}
- **Priority**: {feature.priority.value}
- **Complexity**: {feature.complexity.value}
- **Impact**: {feature.impact.value}
"""

    # Create new task
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    default_config = PhaseConfig()
    task = Task(
        id=task_id,
        title=feature.title,
        description=description,
        status=TaskStatus.BACKLOG,
        phases={
            "planning": Phase(name="planning", config=default_config),
            "coding": Phase(name="coding", config=default_config),
            "validation": Phase(name="validation", config=default_config),
        },
        created_at=datetime.now(),
        updated_at=datetime.now()
    )

    task_storage.create_task(task)

    # Link feature to task and update status
    roadmap_storage.update_feature(feature_id, {
        "task_id": task_id,
        "status": FeatureStatus.IN_PROGRESS
    })

    return {
        "message": "Task created from feature",
        "task_id": task_id,
        "task": task.model_dump(mode="json")
    }


# ============== Analysis Status ==============

@router.get("/roadmap/analysis-status")
async def get_analysis_status():
    """Check what analysis data exists."""
    storage = get_storage()
    return storage.get_analysis_status()


# ============== AI Generation Endpoints ==============

class AnalyzeRequest(BaseModel):
    project_name: str = Field(default="", max_length=200)
    project_description: str = Field(default="", max_length=5000)
    target_audience: str = Field(default="", max_length=1000)


@router.post("/roadmap/analyze")
async def analyze_project_endpoint(data: AnalyzeRequest | None = None):
    """Phase 1: Analyze project structure and auto-detect project info."""
    storage = get_storage()
    roadmap = storage.get_roadmap()

    if not roadmap:
        roadmap = Roadmap()

    # Get active project path
    project_path = Path(get_active_project_path())

    # Auto-extract project info if not provided
    if not data or (not data.project_name and not data.project_description):
        # Use AI to extract project info from files
        project_info = await roadmap_ai.extract_project_info(project_path)
        roadmap.project_name = project_info["project_name"]
        roadmap.project_description = project_info["description"]
        roadmap.target_audience = project_info["target_audience"]
    else:
        # Use provided data
        if data.project_name:
            roadmap.project_name = data.project_name
        if data.project_description:
            roadmap.project_description = data.project_description
        if data.target_audience:
            roadmap.target_audience = data.target_audience

    # Run analysis with active project path
    analysis = await roadmap_ai.analyze_project(project_path)
    roadmap.analysis = analysis
    storage.save_roadmap(roadmap)

    return {
        "analysis": analysis.model_dump(mode="json"),
        "roadmap": roadmap.model_dump(mode="json")
    }


class DiscoverRequest(BaseModel):
    use_existing: bool = False


@router.post("/roadmap/discover")
async def discover_competitors(data: DiscoverRequest | None = None):
    """Phase 2: Discover competitor products."""
    storage = get_storage()
    roadmap = storage.get_roadmap()

    if not roadmap:
        raise HTTPException(
            status_code=400,
            detail="No roadmap found. Run analyze first."
        )

    # Get existing competitors if reusing
    existing = None
    if data and data.use_existing and roadmap.competitor_analysis:
        existing = roadmap.competitor_analysis.competitors

    # Discover competitors
    competitor_analysis = await roadmap_ai.discover_competitors(
        project_name=roadmap.project_name,
        project_description=roadmap.project_description,
        existing_competitors=existing
    )

    roadmap.competitor_analysis = competitor_analysis
    storage.save_roadmap(roadmap)

    return {
        "competitor_analysis": competitor_analysis.model_dump(mode="json"),
        "roadmap": roadmap.model_dump(mode="json")
    }


class GenerateRequest(BaseModel):
    use_competitor_analysis: bool = True


@router.post("/roadmap/generate")
async def generate_features(data: GenerateRequest | None = None):
    """Phase 3: Generate feature suggestions using AI."""
    storage = get_storage()
    roadmap = storage.get_roadmap()

    if not roadmap:
        raise HTTPException(
            status_code=400,
            detail="No roadmap found. Run analyze first."
        )

    use_competitors = data.use_competitor_analysis if data else True

    # Get active project path for deep scanning
    project_path = Path(get_active_project_path())

    # Generate features with deep codebase analysis
    new_features = await roadmap_ai.generate_features(
        project_name=roadmap.project_name,
        project_description=roadmap.project_description,
        target_audience=roadmap.target_audience,
        analysis=roadmap.analysis,
        competitor_analysis=roadmap.competitor_analysis if use_competitors else None,
        existing_features=roadmap.features,
        project_path=project_path
    )

    # Add new features to roadmap
    roadmap.features.extend(new_features)
    storage.save_roadmap(roadmap)

    return {
        "features_generated": len(new_features),
        "features": [f.model_dump(mode="json") for f in new_features],
        "roadmap": roadmap.model_dump(mode="json")
    }


@router.post("/roadmap/features/{feature_id}/expand")
async def expand_feature(feature_id: FeatureId):
    """Expand a feature's description using AI."""
    storage = get_storage()
    feature = storage.get_feature(feature_id)

    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    expanded = await roadmap_ai.expand_feature_description(feature)

    # Update feature with expanded description
    updated = storage.update_feature(feature_id, {"description": expanded})

    return {"feature": updated.model_dump(mode="json") if updated else None}


# ============== Utility ==============

@router.delete("/roadmap")
async def clear_roadmap():
    """Clear all roadmap data (for testing/reset)."""
    storage = get_storage()
    storage.clear_roadmap()
    return {"message": "Roadmap cleared"}
