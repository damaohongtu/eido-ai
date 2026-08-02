from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from .config import Settings, validate_release_package
from .protocol import UpdateResponse, parse_update_requests, render_update_manifest


def create_app(
    settings: Settings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings = settings or Settings.from_env()
        validate_release_package(resolved_settings)
        app.state.settings = resolved_settings
        yield

    app = FastAPI(
        title="Eido Extension Update Server",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/updates.xml")
    async def updates(request: Request) -> Response:
        try:
            update_requests = parse_update_requests(request.query_params.getlist("x"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        current_settings: Settings = request.app.state.settings
        download_url = (
            f"{current_settings.public_base_url}/releases/"
            f"{quote(current_settings.extension_version.value, safe='')}/eido-extension.crx"
        )

        responses: list[UpdateResponse] = []
        for item in update_requests:
            if (
                item.extension_id == current_settings.extension_id
                and item.current_version < current_settings.extension_version
            ):
                responses.append(
                    UpdateResponse(
                        extension_id=item.extension_id,
                        version=current_settings.extension_version.value,
                        codebase=download_url,
                        min_chrome_version=current_settings.extension_min_chrome_version,
                    )
                )
            else:
                responses.append(UpdateResponse(extension_id=item.extension_id))

        return Response(
            content=render_update_manifest(responses),
            media_type="application/xml",
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.api_route("/releases/{version}/eido-extension.crx", methods=["GET", "HEAD"])
    async def download_release(version: str, request: Request) -> FileResponse:
        current_settings: Settings = request.app.state.settings
        if version != current_settings.extension_version.value:
            raise HTTPException(status_code=404, detail="release not found")
        return FileResponse(
            current_settings.extension_package_path,
            media_type="application/x-chrome-extension",
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app


app = create_app()
