import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.auth import RequireReader
from app.config import Settings, get_settings
from app.schemas import EvalReport, EvalReportList, EvalReportSummary

router = APIRouter(prefix="/eval", tags=["evaluation"])

# The only file names ever served. A strict allowlist beats sanitising: there is nothing to
# traverse because the name is matched against a fixed shape and mapped to `<name>.md` inside one
# directory. Scratch files (run logs, JSON dumps) never match.
_REPORT_NAME = re.compile(
    r"^(?P<kind>retrieval|qa|consistency)-(?P<date>\d{4}-\d{2}-\d{2})(?P<smoke>-smoke)?$"
)

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/reports", response_model=EvalReportList, dependencies=[RequireReader])
def list_reports(settings: SettingsDep) -> EvalReportList:
    """Reports written by the evaluation runners, newest first."""
    directory = settings.eval_results_dir
    items: list[EvalReportSummary] = []
    if directory.is_dir():
        for path in directory.glob("*.md"):
            match = _REPORT_NAME.match(path.stem)
            if match:
                items.append(
                    EvalReportSummary(
                        name=path.stem,
                        kind=match["kind"],
                        date=match["date"],
                        smoke=bool(match["smoke"]),
                        size_bytes=path.stat().st_size,
                    )
                )
    items.sort(key=lambda r: (r.date, r.name), reverse=True)
    return EvalReportList(items=items)


@router.get("/reports/{name}", response_model=EvalReport, dependencies=[RequireReader])
def get_report(name: str, settings: SettingsDep) -> EvalReport:
    if not _REPORT_NAME.match(name):
        raise HTTPException(status_code=404, detail="Report not found")
    path = settings.eval_results_dir / f"{name}.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return EvalReport(name=name, markdown=path.read_text(encoding="utf-8"))
