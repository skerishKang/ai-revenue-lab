from starlette.responses import JSONResponse, Response


NO_INDEX_HEADERS: dict[str, str] = {
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
}


RESTRICTIVE_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private, "
                     "max-age=0, s-maxage=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Surrogate-Control": "no-store",
}


def restrictive_cache_response(
    content: dict | list | str | None = None,
    status_code: int = 200,
) -> Response:
    headers = {**RESTRICTIVE_CACHE_HEADERS, **NO_INDEX_HEADERS}
    if content is None:
        return Response(status_code=status_code, headers=headers)
    return JSONResponse(
        content=content,
        status_code=status_code,
        headers=headers,
    )


def no_index_response(
    content: dict | list | str | None = None,
    status_code: int = 200,
) -> Response:
    headers = dict(NO_INDEX_HEADERS)
    if content is None:
        return Response(status_code=status_code, headers=headers)
    return JSONResponse(
        content=content,
        status_code=status_code,
        headers=headers,
    )


def private_json_response(
    content: dict | list,
    status_code: int = 200,
) -> JSONResponse:
    headers = {
        **RESTRICTIVE_CACHE_HEADERS,
        **NO_INDEX_HEADERS,
        "Content-Type": "application/json; charset=utf-8",
    }
    return JSONResponse(
        content=content,
        status_code=status_code,
        headers=headers,
    )
