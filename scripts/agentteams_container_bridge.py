#!/usr/bin/env python3
"""Bounded bridge executed inside one HiClaw AgentTeams container.

It keeps every model decision, HiClaw Project/task transition, SceneGuard tool call,
and Worker-owned deliverable inside the corresponding Agent container. The host
runner only validates exact identifiers and advances the finite state machine.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_URL = "http://host.docker.internal:11434/api/chat"
GATEWAY_URL = "http://host.docker.internal:18091"
TOKEN_FILE = Path("/opt/sceneguard-tools/.gateway-token")


def configure_copaw_working_dir() -> None:
    """Make every native HiClaw tool resolve the same default workspace.

    HiClaw projectflow falls back to the process cwd while filesync falls back
    to cwd/.copaw. The normal CoPaw service exports COPAW_WORKING_DIR, but a
    one-shot bridge process does not inherit it. Set the service-equivalent
    location before importing either tool so Project/DAG and shared files stay
    in one native workspace.
    """
    os.environ.setdefault("COPAW_WORKING_DIR", str(Path.cwd() / ".copaw"))




def configure_team_storage(team: str, leader_name: str, members: set[str]) -> None:
    """Bind shared/ to the topology locked by the Leader-side preflight."""
    worker_name = (os.getenv("HICLAW_WORKER_NAME") or "").strip()
    if len(members) != 4 or len(members | {leader_name}) != 5:
        raise RuntimeError("AgentTeams topology must contain one Leader and four unique Workers")
    if worker_name != leader_name and worker_name not in members:
        raise RuntimeError(f"worker {worker_name} is not a member of Team {team}")

    # HiClaw 0.1 can retain a pre-Team Worker row with the same name. Its
    # single-name lookup may return that stale row without team/role, although
    # the authoritative Team object lists the Worker as ready. The host runner
    # first locks the authoritative Team object through the Leader; this bounded
    # adapter then corrects only storage-scope fields in the one-shot process.
    from copaw_worker.sync import FileSync

    original = FileSync._get_worker_info

    def team_scoped_info(sync: Any) -> dict[str, Any]:
        info = dict(original(sync))
        info["team"] = team
        info["role"] = "team_leader" if worker_name == leader_name else "worker"
        return info

    FileSync._get_worker_info = team_scoped_info

def main() -> int:
    configure_copaw_working_dir()
    payload = json.load(sys.stdin)
    workers = payload.get("team_workers")
    if not isinstance(workers, list) or not all(isinstance(item, str) for item in workers):
        raise ValueError("team_workers must be a string list")
    configure_team_storage(
        required_string(payload, "team"),
        required_string(payload, "team_leader"),
        {item.strip() for item in workers if item.strip()},
    )
    mode = required_string(payload, "mode")
    handlers = {
        "leader_init": leader_init,
        "worker_run": worker_run,
        "leader_accept": leader_accept,
        "leader_finalize": leader_finalize,
    }
    if mode not in handlers:
        raise ValueError(f"unsupported mode: {mode}")
    result = asyncio.run(handlers[mode](payload))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") is True else 1


async def leader_init(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = required_string(payload, "project_id")
    room_id = required_string(payload, "room_id")
    tasks = required_task_list(payload)
    first_task = tasks[0]
    expected = {
        "project_id": project_id,
        "job_id": required_string(payload, "job_id"),
        "asset": required_string(payload, "asset"),
        "profile": required_string(payload, "profile"),
        "workflow": "audit->plan->execute->verify",
        "task_ids": ",".join(task["taskId"] for task in tasks),
        "workers": ",".join(task["assignedTo"] for task in tasks),
        "skills": required_string(payload, "skills"),
    }
    decision = native_decision(
        role="scene-guard-leader",
        model=required_string(payload, "model"),
        tool_name="coordinate_agentteams_project",
        description="Bind the Goal/Profile and authorize exactly one four-Worker SceneGuard DAG.",
        expected=expected,
        previous=None,
        max_retries=integer(payload, "max_retries", 2),
    )
    if decision.get("ok") is not True:
        return decision

    from copaw_worker.hooks.tools.filesync import filesync
    from copaw_worker.hooks.tools.projectflow import projectflow
    from copaw_worker.hooks.tools.taskflow import taskflow

    created = tool_payload(
        await projectflow(
            "create_project",
            {
                "projectId": project_id,
                "title": "SceneGuard semifinal zero-operator five-Agent run",
                "source": required_string(payload, "run_id"),
                "requester": "@manager:matrix-local.hiclaw.io:18080",
            },
        )
    )
    if created.get("ok") is not True:
        return fail("create_project", created)

    planned = tool_payload(
        await projectflow("plan_dag", {"projectId": project_id, "tasks": tasks})
    )
    if planned.get("ok") is not True:
        return fail("plan_dag", planned)

    published = tool_payload(
        await filesync("push", {"path": f"shared/projects/{project_id}/"})
    )
    if published.get("ok") is not True:
        return fail("publish_project", published)

    delegated = tool_payload(
        await taskflow(
            "delegate_task",
            {
                "projectId": project_id,
                "taskId": first_task["taskId"],
                "roomId": room_id,
                "spec": required_string(first_task, "spec"),
            },
        )
    )
    if delegated.get("ok") is not True:
        return fail("delegate_first_task", delegated)

    republished = tool_payload(
        await filesync("push", {"path": f"shared/projects/{project_id}/"})
    )
    if republished.get("ok") is not True:
        return fail("republish_project", republished)

    return {
        "ok": True,
        "mode": "leader_init",
        "agent_id": "scene-guard-leader",
        "decision": decision,
        "project": created["project"],
        "planned_tasks": planned["tasks"],
        "delegated_task": delegated["task"],
    }


async def worker_run(payload: dict[str, Any]) -> dict[str, Any]:
    task_id = required_string(payload, "task_id")
    role = required_string(payload, "role")
    stage = required_string(payload, "stage")
    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    skill_ids = payload.get("skill_ids")
    if not isinstance(skill_ids, list) or not all(isinstance(item, str) and item for item in skill_ids):
        raise ValueError("skill_ids must be a non-empty string list")

    from copaw_worker.hooks.tools.taskflow import taskflow

    acknowledged = tool_payload(await taskflow("ack_task", {"taskId": task_id}))
    if acknowledged.get("ok") is not True:
        return fail("ack_task", acknowledged)

    decision = native_decision(
        role=role,
        model=required_string(payload, "model"),
        tool_name={
            "create": "create_scene_job",
            "plan": "freeze_patch_plan",
            "execute": "execute_frozen_plan",
            "verify": "verify_and_finalize",
        }[stage],
        description=required_string(payload, "description"),
        expected={name: str(value) for name, value in arguments.items()},
        previous=payload.get("previous"),
        max_retries=integer(payload, "max_retries", 2),
    )
    if decision.get("ok") is not True:
        return decision

    tool_result = gateway_call(stage, arguments)
    if tool_result.get("ok") is not True:
        return fail("gateway_call", tool_result)

    task_dir = workspace_dir() / "shared" / "tasks" / task_id
    output_dir = task_dir / "workspace"
    output_dir.mkdir(parents=True, exist_ok=True)
    tool_path = output_dir / "tool-result.json"
    skill_path = output_dir / "skill-usage.json"
    write_json(tool_path, tool_result)
    write_json(
        skill_path,
        {
            "schema_version": "0.1",
            "agent_id": role,
            "task_id": task_id,
            "skill_ids": skill_ids,
            "tool_name": decision["tool"],
            "decision_sha256": decision["decision_sha256"],
            "tool_result_sha256": canonical_sha256(tool_result),
        },
    )

    deliverables = [
        f"shared/tasks/{task_id}/workspace/tool-result.json",
        f"shared/tasks/{task_id}/workspace/skill-usage.json",
    ]
    submitted = tool_payload(
        await taskflow(
            "submit_task",
            {
                "taskId": task_id,
                "status": "SUCCESS",
                "summary": f"{role} completed {stage} with validated machine evidence.",
                "deliverables": deliverables,
                "notes": [f"skills={','.join(skill_ids)}"],
            },
        )
    )
    if submitted.get("ok") is not True:
        return fail("submit_task", submitted)

    return {
        "ok": True,
        "mode": "worker_run",
        "agent_id": role,
        "task_id": task_id,
        "stage": stage,
        "skill_ids": skill_ids,
        "decision": decision,
        "tool_result": tool_result,
        "tool_result_sha256": canonical_sha256(tool_result),
        "submitted": submitted,
    }


async def leader_accept(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = required_string(payload, "project_id")
    completed_task_id = required_string(payload, "completed_task_id")
    next_task = payload.get("next_task")

    from copaw_worker.hooks.tools.filesync import filesync
    from copaw_worker.hooks.tools.projectflow import projectflow
    from copaw_worker.hooks.tools.taskflow import taskflow
    from copaw_worker.task import DagTask, parse_dag_tasks, replace_dag_tasks
    from copaw_worker.hooks.tools.projectflow import _store

    checked = tool_payload(await taskflow("check_task", {"taskId": completed_task_id}))
    if checked.get("ok") is not True or checked.get("effective") is not True:
        return fail("check_task", checked)

    store = _store()
    plan = store.read_project_plan(project_id)
    tasks = parse_dag_tasks(plan)
    if completed_task_id not in {task.task_id for task in tasks}:
        return fail("accept_task", {"error": "completed task is absent from Project DAG"})
    updated = [
        DagTask(
            task_id=task.task_id,
            title=task.title,
            assigned_to=task.assigned_to,
            depends_on=task.depends_on,
            status="completed" if task.task_id == completed_task_id else task.status,
        )
        for task in tasks
    ]
    store.write_project_plan(project_id, replace_dag_tasks(plan, updated))

    pushed = tool_payload(await filesync("push", {"path": f"shared/projects/{project_id}/"}))
    if pushed.get("ok") is not True:
        return fail("publish_acceptance", pushed)

    ready = tool_payload(await projectflow("ready_nodes", {"projectId": project_id}))
    if ready.get("ok") is not True:
        return fail("ready_nodes", ready)

    delegated = None
    if next_task is not None:
        if not isinstance(next_task, dict):
            raise ValueError("next_task must be an object or null")
        next_id = required_string(next_task, "taskId")
        ready_ids = {item["task_id"] for item in ready.get("readyNodes", [])}
        if next_id not in ready_ids:
            return fail("ready_node_contract", {"expected": next_id, "actual": sorted(ready_ids)})
        delegated = tool_payload(
            await taskflow(
                "delegate_task",
                {
                    "projectId": project_id,
                    "taskId": next_id,
                    "roomId": required_string(payload, "room_id"),
                    "spec": required_string(next_task, "spec"),
                },
            )
        )
        if delegated.get("ok") is not True:
            return fail("delegate_next_task", delegated)
        pushed = tool_payload(
            await filesync("push", {"path": f"shared/projects/{project_id}/"})
        )
        if pushed.get("ok") is not True:
            return fail("publish_delegation", pushed)

    return {
        "ok": True,
        "mode": "leader_accept",
        "agent_id": "scene-guard-leader",
        "accepted_task_id": completed_task_id,
        "checked_result": checked["result"],
        "ready_nodes": ready.get("readyNodes", []),
        "delegated_task": delegated.get("task") if delegated else None,
    }


async def leader_finalize(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = required_string(payload, "project_id")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("result must be an object")

    from copaw_worker.hooks.tools.filesync import filesync
    from copaw_worker.hooks.tools.projectflow import projectflow
    from copaw_worker.hooks.tools.projectflow import _store
    from copaw_worker.task import parse_dag_tasks

    store = _store()
    tasks = parse_dag_tasks(store.read_project_plan(project_id))
    if not tasks or any(task.status != "completed" for task in tasks):
        return fail(
            "complete_project_gate",
            {"task_statuses": {task.task_id: task.status for task in tasks}},
        )

    project_dir = workspace_dir() / "shared" / "projects" / project_id
    write_json(project_dir / "result.json", result)
    (project_dir / "result.md").write_text(
        "# SceneGuard five-Agent result\n\n"
        f"STATUS: {result.get('status')}\n\n"
        f"GATE: {result.get('gate_state')}\n\n"
        f"JOB_ID: {result.get('job_id')}\n\n"
        f"EVIDENCE_SHA256: {canonical_sha256(result)}\n",
        encoding="utf-8",
    )
    completed = tool_payload(
        await projectflow("complete_project", {"projectId": project_id})
    )
    if completed.get("ok") is not True:
        return fail("complete_project", completed)
    pushed = tool_payload(
        await filesync("push", {"path": f"shared/projects/{project_id}/"})
    )
    if pushed.get("ok") is not True:
        return fail("publish_final_project", pushed)
    return {
        "ok": True,
        "mode": "leader_finalize",
        "agent_id": "scene-guard-leader",
        "project": completed["project"],
        "result_sha256": canonical_sha256(result),
        "project_result_paths": [
            f"shared/projects/{project_id}/result.json",
            f"shared/projects/{project_id}/result.md",
        ],
    }


def native_decision(
    *,
    role: str,
    model: str,
    tool_name: str,
    description: str,
    expected: dict[str, str],
    previous: Any,
    max_retries: int,
) -> dict[str, Any]:
    properties = {name: {"type": "string"} for name in expected}
    tool = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description,
            "parameters": {
                "type": "object",
                "required": list(expected),
                "properties": properties,
                "additionalProperties": False,
            },
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                f"You are the SceneGuard {role} Agent inside your dedicated AgentTeams container. "
                f"Your authorization is exactly one tool: {tool_name}. Call it once with unchanged "
                "identifiers. Do not invent geometry facts or change the workflow."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Required arguments: {json.dumps(expected, ensure_ascii=False)}\n"
                f"Upstream machine evidence: {json.dumps(previous, ensure_ascii=False, separators=(',', ':'))}"
            ),
        },
    ]
    last_error = "no attempt"
    for attempt in range(1, max_retries + 2):
        response = post_json(
            OLLAMA_URL,
            {
                "model": model,
                "messages": messages,
                "tools": [tool],
                "stream": False,
                "think": False,
                "options": {"temperature": 0},
            },
            headers={"Content-Type": "application/json"},
            timeout=180,
        )
        calls = response.get("message", {}).get("tool_calls", [])
        if len(calls) == 1:
            function = calls[0].get("function", {})
            arguments = function.get("arguments")
            if function.get("name") == tool_name and arguments == expected:
                decision = {
                    "role": role,
                    "model": model,
                    "tool": tool_name,
                    "arguments": arguments,
                    "attempt_count": attempt,
                    "decision_runtime": "inside_agentteams_container",
                }
                decision["decision_sha256"] = canonical_sha256(
                    {"tool": tool_name, "arguments": arguments}
                )
                return {"ok": True, **decision}
            last_error = "tool name or exact arguments did not match"
        else:
            last_error = f"expected one native tool call, observed {len(calls)}"
        messages.append(
            {"role": "assistant", "content": response.get("message", {}).get("content", "")}
        )
        messages.append(
            {"role": "user", "content": f"Schema retry {attempt}: {last_error}. Call the supplied tool."}
        )
    return {"ok": False, "error": last_error, "attempt_count": max_retries + 1}


def gateway_call(stage: str, arguments: dict[str, Any]) -> dict[str, Any]:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Gateway token file is empty")
    if stage == "create":
        path = "/v1/jobs"
        body = {
            "asset": required_string(arguments, "asset"),
            "profile": required_string(arguments, "profile"),
            "job_id": required_string(arguments, "job_id"),
        }
    elif stage == "plan":
        path = "/v1/tools/repair.plan"
        body = {
            "job_id": required_string(arguments, "job_id"),
            "profile": required_string(arguments, "profile"),
        }
    elif stage in {"execute", "verify"}:
        path = {
            "execute": "/v1/tools/repair.execute",
            "verify": "/v1/tools/regression.verify",
        }[stage]
        body = {
            "job_id": required_string(arguments, "job_id"),
            "profile": required_string(arguments, "profile"),
            "plan_id": required_string(arguments, "plan_id"),
        }
    else:
        raise ValueError(f"unsupported worker stage: {stage}")
    return post_json(
        GATEWAY_URL + path,
        body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        timeout=90,
    )


def tool_payload(response: Any) -> dict[str, Any]:
    content = getattr(response, "content", None)
    if not isinstance(content, list) or not content:
        raise ValueError("HiClaw tool returned no content")
    block = content[0]
    text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
    if not isinstance(text, str):
        raise ValueError("HiClaw tool returned non-text content")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("HiClaw tool returned non-object JSON")
    return payload


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"ok": False, "error": {"code": "HTTP_ERROR", "message": raw}}
        result["http_status"] = exc.code
    except (OSError, URLError) as exc:
        result = {"ok": False, "error": {"code": "CONNECTION_ERROR", "message": str(exc)}}
    if not isinstance(result, dict):
        raise ValueError("HTTP endpoint returned non-object JSON")
    return result


def workspace_dir() -> Path:
    configured = os.getenv("COPAW_WORKING_DIR")
    if configured:
        return Path(configured) / "workspaces" / "default"
    cwd = Path.cwd()
    if cwd.name == "default" and cwd.parent.name == "workspaces":
        return cwd
    raise ValueError("cannot resolve CoPaw default workspace")


def required_task_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 4:
        raise ValueError("tasks must contain exactly four DAG nodes")
    required = {"taskId", "title", "assignedTo", "dependsOn", "spec"}
    for task in tasks:
        if not isinstance(task, dict) or not required.issubset(task):
            raise ValueError("each task is missing a required DAG/spec field")
        if not isinstance(task["dependsOn"], list):
            raise ValueError("dependsOn must be a list")
    return tasks


def required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def integer(payload: dict[str, Any], name: str, default: int) -> int:
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fail(step: str, evidence: Any) -> dict[str, Any]:
    return {"ok": False, "failed_step": step, "evidence": evidence}


if __name__ == "__main__":
    raise SystemExit(main())
