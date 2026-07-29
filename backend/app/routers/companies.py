from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, graph_pipeline, schemas
from app.db import get_session
from app.extraction.base import Extractor

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("", response_model=list[schemas.CompanyOut])
def list_companies(session: Session = Depends(get_session)):
    return crud.list_companies(session)


@router.post("", response_model=schemas.CompanyOut, status_code=201)
def create_company(
    payload: schemas.CompanyCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    extractor: Extractor = Depends(graph_pipeline.get_default_extractor),
    session_factory=Depends(graph_pipeline.get_default_session_factory),
):
    try:
        company = crud.create_company(
            session,
            name=payload.name,
            meta=payload.meta,
            checks=payload.checks,
            notes=payload.notes,
            buckets=payload.buckets,
            dm=payload.dm,
        )
    except crud.DuplicateNameError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    background_tasks.add_task(graph_pipeline.run_graph_extraction, company.id, extractor, session_factory)
    return company


@router.put("/{company_id}", response_model=schemas.CompanyOut)
def update_company(
    company_id: int,
    payload: schemas.CompanyUpdate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    extractor: Extractor = Depends(graph_pipeline.get_default_extractor),
    session_factory=Depends(graph_pipeline.get_default_session_factory),
):
    try:
        company = crud.update_company(
            session,
            company_id,
            meta=payload.meta,
            checks=payload.checks,
            notes=payload.notes,
            buckets=payload.buckets,
            dm=payload.dm,
        )
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail="company not found") from e
    background_tasks.add_task(graph_pipeline.run_graph_extraction, company.id, extractor, session_factory)
    return company


@router.post("/{company_id}/rename", response_model=schemas.CompanyOut)
def rename_company(
    company_id: int,
    payload: schemas.CompanyRename,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    extractor: Extractor = Depends(graph_pipeline.get_default_extractor),
    session_factory=Depends(graph_pipeline.get_default_session_factory),
):
    try:
        company = crud.rename_company(session, company_id, payload.new_name)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail="company not found") from e
    except crud.DuplicateNameError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    # keeps the graph's Company node name in sync — see graph_crud.ensure_company_node
    background_tasks.add_task(graph_pipeline.run_graph_extraction, company.id, extractor, session_factory)
    return company
