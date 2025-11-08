"""FastAPI application exposing background transcription jobs."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .tasks import JobState, TaskManager

app = FastAPI(title="Whisper GUI Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class JobResponse(BaseModel):
    id: str


class JobStateResponse(JobState):
    class Config:
        orm_mode = True


def get_task_manager() -> TaskManager:
    base_dir = Path(__file__).resolve().parents[2]
    if not hasattr(get_task_manager, "_manager"):
        get_task_manager._manager = TaskManager(base_dir=base_dir)  # type: ignore[attr-defined]
    return get_task_manager._manager  # type: ignore[attr-defined]


@app.post("/jobs", response_model=JobResponse)
async def create_job(
    file: Optional[UploadFile] = File(default=None),
    url: Optional[str] = Form(default=None),
    manager: TaskManager = Depends(get_task_manager),
) -> JobResponse:
    if not file and not url:
        raise HTTPException(status_code=400, detail="Either file or url must be provided")
    if file and url:
        raise HTTPException(status_code=400, detail="Provide either file or url, not both")

    if file:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        job_id = manager.create_job_from_upload(file.filename, data)
    else:
        assert url is not None
        job_id = manager.create_job_from_url(url)
    return JobResponse(id=job_id)


@app.get("/jobs/{job_id}", response_model=JobStateResponse)
async def get_job(job_id: str, manager: TaskManager = Depends(get_task_manager)) -> JobState:
    state = manager.get_job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    return state


@app.get("/jobs/{job_id}/download")
async def download_result(job_id: str, manager: TaskManager = Depends(get_task_manager)) -> FileResponse:
    result_path = manager.get_job_result(job_id)
    if not result_path:
        raise HTTPException(status_code=404, detail="Result not available")
    return FileResponse(path=result_path, filename=result_path.name)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    manager = get_task_manager()
    manager.shutdown()
