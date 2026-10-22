from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from backend.api.uploads import MAX_UPLOAD_BYTES, UploadError, save_upload

upload_router = APIRouter()

# Margem para o overhead do multipart (cabeçalhos, boundary).
_MAX_CONTENT_LENGTH = MAX_UPLOAD_BYTES + 64 * 1024


@upload_router.post("/{thread_id}")
async def upload_attachment(
    thread_id: str,
    request: Request,
    workspace_path: str = Form(...),
    file: UploadFile = File(...),
):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_CONTENT_LENGTH:
        raise HTTPException(status_code=413, detail="Arquivo maior que o limite permitido.")

    try:
        return await save_upload(workspace_path, thread_id, file.filename or "", file.read)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
