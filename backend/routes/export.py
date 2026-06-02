"""
Export routes.
Handles generating and downloading transcript/summary exports.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

try:
    from ..auth import require_authenticated_request
    from ..models.database import get_meeting, get_meeting_segments
    from ..services.export import (
        export_transcript_txt,
        export_transcript_md,
        export_transcript_docx,
        export_transcript_pdf,
        export_summary_txt,
        export_summary_md,
        export_summary_docx,
        export_summary_pdf,
    )
except ImportError:
    from auth import require_authenticated_request
    from models.database import get_meeting, get_meeting_segments
    from services.export import (
        export_transcript_txt,
        export_transcript_md,
        export_transcript_docx,
        export_transcript_pdf,
        export_summary_txt,
        export_summary_md,
        export_summary_docx,
        export_summary_pdf,
    )

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/transcript/{meeting_id}/{format}")
async def export_transcript(meeting_id: str, format: str, request: Request):
    """
    Export meeting transcript in the specified format.
    Supported formats: txt, md, docx, pdf
    """
    require_authenticated_request(request)
    meeting = await get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    segments = await get_meeting_segments(meeting_id)

    exporters = {
        "txt": export_transcript_txt,
        "md": export_transcript_md,
        "docx": export_transcript_docx,
        "pdf": export_transcript_pdf,
    }

    if format not in exporters:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {format}. Use: txt, md, docx, pdf",
        )

    filepath = exporters[format](meeting, segments)
    if not filepath:
        raise HTTPException(
            status_code=500,
            detail=f"Export failed. Required library may not be installed.",
        )

    media_types = {
        "txt": "text/plain",
        "md": "text/markdown",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }

    return FileResponse(
        path=str(filepath),
        filename=filepath.name,
        media_type=media_types.get(format, "application/octet-stream"),
    )


@router.get("/summary/{meeting_id}/{format}")
async def export_summary(meeting_id: str, format: str, request: Request):
    """
    Export meeting summary in the specified format.
    Supported formats: txt, md, docx, pdf
    """
    require_authenticated_request(request)
    meeting = await get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    exporters = {
        "txt": export_summary_txt,
        "md": export_summary_md,
        "docx": export_summary_docx,
        "pdf": export_summary_pdf,
    }

    if format not in exporters:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {format}. Use: txt, md, docx, pdf",
        )

    filepath = exporters[format](meeting)
    if not filepath:
        raise HTTPException(
            status_code=500,
            detail=f"Export failed. Required library may not be installed.",
        )

    media_types = {
        "txt": "text/plain",
        "md": "text/markdown",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }

    return FileResponse(
        path=str(filepath),
        filename=filepath.name,
        media_type=media_types.get(format, "application/octet-stream"),
    )
