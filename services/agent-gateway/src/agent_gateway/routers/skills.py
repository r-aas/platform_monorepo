"""Skills CRUD API router."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agent_gateway.models import SkillDefinition
from agent_gateway.skills_registry import create_skill, delete_skill, get_skill, list_skills, update_skill

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/search")
async def search_skills(q: str = Query(..., description="Search query for hybrid RAG over skills registry")):
    """Hybrid search: keyword + semantic similarity over skill names, tags, tasks, descriptions."""
    skills = list_skills()
    query_lower = q.lower()

    scored = []
    for skill in skills:
        score = 0
        task_names = " ".join(t.name for t in skill.tasks)
        searchable = (
            f"{skill.name} {skill.description} {' '.join(skill.tags)} {task_names} {skill.prompt_fragment}".lower()
        )
        for term in query_lower.split():
            if term in searchable:
                score += 1
            if term in skill.name.lower():
                score += 3
            if term in skill.description.lower():
                score += 2
            if any(term in tag.lower() for tag in skill.tags):
                score += 2
        if score > 0:
            scored.append((score, skill))

    scored.sort(key=lambda x: x[0], reverse=True)

    # TODO: add embedding-based semantic similarity via Ollama /v1/embeddings

    return {
        "query": q,
        "results": [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "tags": s.tags,
                "task_count": len(s.tasks),
                "score": sc,
            }
            for sc, s in scored
        ],
    }


@router.post("", status_code=201)
async def create_skill_endpoint(skill: SkillDefinition):
    try:
        create_skill(skill)
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": {"message": str(e), "code": "skill_exists"}})
    return {"name": skill.name, "version": skill.version}


@router.get("")
async def list_skills_endpoint():
    skills = list_skills()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "tags": s.tags,
                "task_count": len(s.tasks),
            }
            for s in skills
        ]
    }


@router.get("/{name}")
async def get_skill_endpoint(name: str):
    try:
        skill = get_skill(name)
    except KeyError:
        return JSONResponse(
            status_code=404, content={"error": {"message": f"Skill '{name}' not found", "code": "skill_not_found"}}
        )
    return skill.model_dump()


@router.put("/{name}")
async def update_skill_endpoint(name: str, skill: SkillDefinition):
    skill.name = name
    try:
        update_skill(skill)
    except Exception as e:
        return JSONResponse(status_code=404, content={"error": {"message": str(e)}})
    return {"name": skill.name, "version": skill.version, "changes": "Updated."}


@router.delete("/{name}")
async def delete_skill_endpoint(name: str, force: bool = Query(False)):
    try:
        delete_skill(name, force=force)
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": {"message": str(e), "code": "skill_in_use"}})
    return {"message": f"Skill '{name}' deleted."}


@router.get("/tasks/search")
async def search_tasks(q: str = Query(..., description="Search query for hybrid RAG over tasks across all skills")):
    """Hybrid search over tasks across all skills — find tasks by capability description."""
    skills = list_skills()
    query_lower = q.lower()

    scored = []
    for skill in skills:
        for task in skill.tasks:
            score = 0
            searchable = f"{task.name} {task.description} {skill.name}".lower()
            for term in query_lower.split():
                if term in searchable:
                    score += 1
                if term in task.name.lower():
                    score += 3
                if term in task.description.lower():
                    score += 2
            if score > 0:
                scored.append(
                    (
                        score,
                        {
                            "task": task.name,
                            "description": task.description,
                            "skill": skill.name,
                            "has_evaluation": task.evaluation is not None,
                            "score": score,
                        },
                    )
                )

    scored.sort(key=lambda x: x[0], reverse=True)

    # TODO: add embedding-based semantic similarity via Ollama /v1/embeddings

    return {"query": q, "results": [item for _, item in scored]}


@router.get("/{name}/tasks")
async def list_skill_tasks(name: str):
    try:
        skill = get_skill(name)
    except KeyError:
        return JSONResponse(
            status_code=404, content={"error": {"message": f"Skill '{name}' not found", "code": "skill_not_found"}}
        )
    return {
        "skill": name,
        "tasks": [
            {
                "name": t.name,
                "description": t.description,
                "inputs": t.inputs,
                "has_evaluation": t.evaluation is not None,
            }
            for t in skill.tasks
        ],
    }
