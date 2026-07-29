from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, graph_crud, schemas
from app.db import get_session

router = APIRouter(prefix="/api/companies", tags=["graph"])


@router.get("/{company_id}/graph", response_model=schemas.GraphOut)
def get_company_graph(company_id: int, session: Session = Depends(get_session)):
    try:
        crud.get_company(session, company_id)
    except crud.NotFoundError as e:
        raise HTTPException(status_code=404, detail="company not found") from e
    return graph_crud.get_graph(session, company_id)
