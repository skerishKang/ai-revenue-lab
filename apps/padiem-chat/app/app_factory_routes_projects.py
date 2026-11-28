from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .project_file_routes import (
    owner_files_collection,
    project_file_detail,
    project_file_original,
    project_files_collection,
)

from .tus_project_upload import project_file_tus_collection, project_file_tus_item

from .document_convert_page_image import convert_item_original_page

from .document_convert_routes import (
    convert_item_detail,
    convert_item_delete,
    convert_item_markdown,
    convert_item_original,
    convert_item_review,
    convert_item_run,
    convert_job_archive,
    convert_job_delete,
    convert_job_detail,
    convert_job_files,
    convert_jobs_collection,
    drain_background_runs,
)

from .drive_case_folder_routes import (
    drive_case_folder_delete,
    drive_case_folder_put,
    drive_case_folder_status,
    drive_folders_collection,
)

from .drive_case_pdf_routes import (
    drive_case_pdf_detail,
    drive_case_pdf_extraction_review,
    drive_case_pdfs_collection,
)

from .project_routes import project_detail, projects_collection

from .saved_output_routes import output_detail, outputs_collection

def register_project_document_routes(routes: list) -> None:
    routes.extend([
        Route("/api/projects", projects_collection, methods=["GET", "POST"]),
        # #4489: one owner-scoped keyset-paginated read over every stored project file,
        # so the Library can walk a full history without per-project fan-out.
        Route("/api/project-files", owner_files_collection, methods=["GET"]),
        Route("/api/projects/{project_id}", project_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/projects/{project_id}/files", project_files_collection, methods=["GET", "POST"]),
        # 1GB 통일 1단계 — tus 1.0.0 resumable chunked upload for project binaries.
        # Registered before the {file_id} catch-all so "tus" is never read as a
        # file id. See app/tus_project_upload.py.
        Route("/api/projects/{project_id}/files/tus", project_file_tus_collection, methods=["POST", "OPTIONS"]),
        Route("/api/projects/{project_id}/files/tus/{upload_id}", project_file_tus_item, methods=["HEAD", "PATCH", "GET"]),
        Route("/api/projects/{project_id}/files/{file_id}/original", project_file_original, methods=["GET"]),
        Route("/api/projects/{project_id}/files/{file_id}", project_file_detail, methods=["GET", "DELETE", "PUT"]),
        # #5568 PDF→Markdown utility: a work ledger per upload session, one conversion
        # per item, and owner-scoped reads of both the original and the result.
        Route("/api/document-conversions", convert_jobs_collection, methods=["GET", "POST"]),
        Route("/api/document-conversions/{job_id}", convert_job_detail, methods=["GET"]),
        Route("/api/document-conversions/{job_id}", convert_job_delete, methods=["DELETE"]),
        Route("/api/document-conversions/{job_id}/files", convert_job_files, methods=["POST"]),
        Route("/api/document-conversions/{job_id}/archive", convert_job_archive, methods=["GET"]),
        Route("/api/document-conversions/items/{item_id}", convert_item_detail, methods=["GET"]),
        Route("/api/document-conversions/items/{item_id}", convert_item_delete, methods=["DELETE"]),
        Route("/api/document-conversions/items/{item_id}/run", convert_item_run, methods=["POST"]),
        Route("/api/document-conversions/items/{item_id}/review", convert_item_review, methods=["POST"]),
        Route("/api/document-conversions/items/{item_id}/markdown", convert_item_markdown, methods=["GET"]),
        Route("/api/document-conversions/items/{item_id}/original", convert_item_original, methods=["GET"]),
        Route(
            "/api/document-conversions/items/{item_id}/original/{page_no}.jpeg",
            convert_item_original_page,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-folder",
            drive_case_folder_status,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-folder",
            drive_case_folder_put,
            methods=["PUT"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-folder",
            drive_case_folder_delete,
            methods=["DELETE"],
        ),
        Route(
            "/api/projects/{project_id}/drive-folders",
            drive_folders_collection,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-pdfs",
            drive_case_pdfs_collection,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-pdfs/{file_id}",
            drive_case_pdf_detail,
            methods=["GET"],
        ),
        Route(
            "/api/projects/{project_id}/drive-case-pdfs/{file_id}/browser-extraction",
            drive_case_pdf_extraction_review,
            methods=["POST"],
        ),
        Route("/api/outputs", outputs_collection, methods=["GET", "POST"]),
        Route("/api/outputs/{output_id}", output_detail, methods=["GET", "PATCH", "DELETE"]),
    ])
