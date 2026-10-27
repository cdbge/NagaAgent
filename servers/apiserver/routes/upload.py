#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档上传与列表。

为什么单独补这个模块
==================

上游在提交 `684905c 修复了文件上传Not Found的问题` 里，给
`apiserver/api_server.py` 加了 `/upload/document`。

本 fork 把这个文件按域拆成了 `routes/*.py`，拆分时该端点没有跟着迁移，
于是 `ui/controller/tool_document.py` 里 POST 到 `/upload/document` 仍然 404
——「上传文档」功能是坏的。

这里按现有约定把它补回：一个模块导出一个 `router`，由 `api_server.py`
末尾统一 include。

约定：
  * 文件落在仓库根的 `uploaded_documents/`
  * 响应字段与 `tool_document.py` 的解析保持一致（filename / file_path / ...）
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..api_server import logger

router = APIRouter(tags=["文档"])

#: 上传目录（相对仓库根；api_server 启动时工作目录已在仓库根）
UPLOAD_DIR = Path("uploaded_documents")


class FileUploadResponse(BaseModel):
    """单个文件上传结果。"""

    filename: str
    file_path: str
    file_size: int
    file_type: str
    upload_time: str


class DocumentListResponse(BaseModel):
    """已完成上传的文档列表。"""

    status: str = "success"
    documents: List[dict]
    total: int


def _ensure_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


@router.post("/upload/document", response_model=FileUploadResponse)
async def upload_document(file: UploadFile = File(...),
                          description: Optional[str] = Form(None)):
    """上传文档，保存到 `uploaded_documents/`。"""
    try:
        upload_dir = _ensure_dir()
        filename = Path(file.filename or "unnamed").name  # 去掉路径，防目录穿越
        target = upload_dir / filename

        with open(target, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                buffer.write(chunk)

        stat = target.stat()
        logger.info(f"[文档] 已接收 {filename}（{stat.st_size} 字节）")
        return FileUploadResponse(
            filename=filename,
            file_path=str(target.resolve()),
            file_size=stat.st_size,
            file_type=target.suffix,
            upload_time=time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(stat.st_mtime)),
        )
    except Exception as exc:
        logger.error(f"[文档] 上传失败: {exc}")
        raise HTTPException(status_code=500, detail=f"上传失败: {exc}")


@router.get("/upload/documents", response_model=DocumentListResponse)
async def list_uploaded_documents():
    """列出已上传的文档。"""
    try:
        upload_dir = _ensure_dir()
        docs = []
        for path in sorted(upload_dir.iterdir()):
            if not path.is_file():
                continue
            stat = path.stat()
            docs.append({
                "filename": path.name,
                "file_path": str(path.resolve()),
                "file_size": stat.st_size,
                "file_type": path.suffix,
                "upload_time": time.strftime("%Y-%m-%d %H:%M:%S",
                                             time.localtime(stat.st_mtime)),
            })
        return DocumentListResponse(documents=docs, total=len(docs))
    except Exception as exc:
        logger.error(f"[文档] 列表失败: {exc}")
        raise HTTPException(status_code=500, detail=f"列表失败: {exc}")
