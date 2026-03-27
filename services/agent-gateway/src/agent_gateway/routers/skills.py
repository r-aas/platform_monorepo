"""Skills CRUD API router."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agent_gateway.benchmark.runner import run_benchmark_task
from agent_gateway.config import Settings
from agent_gateway.embeddings import cosine_similarity, get_embedding, hybrid_score
from agent_gateway.models import SkillDefinition
from agent_gateway.skills_registry import create_skill, delete_skill, get_skill, list_skills, update_skill

_settings = Settings()

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/search")
async def search_skills(q: str = Query(..., description="Search query for hybrid RAG over skills registry")):
    """Hybrid search: keyword + semantic similarity over skill names, tags, tasks, descriptions."""
    skills = await list_skills()
    query_lower = q.lower()

    query_emb = await get_embedding(q)
    scored = []
    for skill in skills:
        kw_score = 0
        task_names = " ".join(t.name for t in skill.tasks)
        searchable = (
            f"{skill.name} {skill.description} {' '.join(skill.tags)} {task_names} {skill.prompt_fragment}".lower()
        )
        for term in query_lower.split():
            if term in searchable:
                kw_score += 1
            if term in skill.name.lower():
                kw_score += 3
            if term in skill.description.lower():
                kw_score += 2
            if any(term in tag.lower() for tag in skill.tags):
                kw_score += 2

        emb_sim = None
        if query_emb is not None:
            skill_text = f"{skill.name} {skill.description} {' '.join(skill.tags)}"
            skill_emb = await get_embedding(skill_text)
            if skill_emb is not None:
                emb_sim = cosine_similarity(query_emb, skill_emb)

        score = hybrid_score(kw_score, emb_sim)
        if score > 0:
            scored.append((score, skill))

    scored.sort(key=lambda x: x[0], reverse=True)

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
        await create_skill(skill)
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": {"message": str(e), "code": "skill_exists"}})
    return {"name": skill.name, "version": skill.version}


@router.get("")
async def list_skills_endpoint():
    skills = await list_skills()
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
        skill = await get_skill(name)
    except KeyError:
        return JSONResponse(
            status_code=404, content={"error": {"message": f"Skill '{name}' not found", "code": "skill_not_found"}}
        )
    return skill.model_dump()


@router.put("/{name}")
async def update_skill_endpoint(name: str, skill: SkillDefinition):
    skill.name = name
    try:
        await update_skill(skill)
    except Exception as e:
        return JSONResponse(status_code=404, content={"error": {"message": str(e)}})
    return {"name": skill.name, "version": skill.version, "changes": "Updated."}


@router.delete("/{name}")
async def delete_skill_endpoint(name: str, force: bool = Query(False)):
    try:
        await delete_skill(name, force)
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": {"message": str(e), "code": "skill_in_use"}})
    return {"message": f"Skill '{name}' deleted."}


@router.get("/tasks/search")
async def search_tasks(q: str = Query(..., description="Search query for hybrid RAG over tasks across all skills")):
    """Hybrid search over tasks across all skills — find tasks by capability description."""
    skills = await list_skills()
    query_lower = q.lower()

    query_emb = await get_embedding(q)
    scored = []
    for skill in skills:
        for task in skill.tasks:
            kw_score = 0
            searchable = f"{task.name} {task.description} {skill.name}".lower()
            for term in query_lower.split():
                if term in searchable:
                    kw_score += 1
                if term in task.name.lower():
                    kw_score += 3
                if term in task.description.lower():
                    kw_score += 2

            emb_sim = None
            if query_emb is not None:
                task_text = f"{task.name} {task.description}"
                task_emb = await get_embedding(task_text)
                if task_emb is not None:
                    emb_sim = cosine_similarity(query_emb, task_emb)

            score = hybrid_score(kw_score, emb_sim)
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

    return {"query": q, "results": [item for _, item in scored]}


@router.get("/{name}/tasks")
async def list_skill_tasks(name: str):
    try:
        skill = await get_skill(name)
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


@router.post("/{name}/tasks/{task}/benchmark", status_code=202)
async def benchmark_task(name: str, task: str, agent: str = Query(..., description="Agent name to run benchmark with")):
    """Run eval dataset for a skill task against an agent. Returns 202 with benchmark run ID."""
    try:
        skill = await get_skill(name)
    except KeyError:
        return JSONResponse(
            status_code=404, content={"error": {"message": f"Skill '{name}' not found", "code": "skill_not_found"}}
        )

    task_def = next((t for t in skill.tasks if t.name == task), None)
    if task_def is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Task '{task}' not found in skill '{name}'", "code": "task_not_found"}},
        )

    if task_def.evaluation is None:
        return JSONResponse(
            status_code=422,
            content={"error": {"message": f"Task '{task}' has no evaluation dataset", "code": "no_evaluation"}},
        )

    run_id = await asyncio.to_thread(
        run_benchmark_task,
        name,
        task,
        agent,
        task_def.evaluation.dataset,
        _settings.mlflow_tracking_uri,
    )
    return {
        "benchmark_id": run_id,
        "skill": name,
        "task": task,
        "agent": agent,
        "status": "completed",
    }
