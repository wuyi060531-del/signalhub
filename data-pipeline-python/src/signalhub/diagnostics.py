"""采集诊断只记录允许字段；异常消息、SQL参数、URL、正文和局部变量不进入日志。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import socket
from types import TracebackType
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


class SourceAccessError(ValueError):
    """安全策略拒绝来源；不能据此认定岗位关闭。"""


def failure_context(exc: Exception, *, stage: str) -> dict[str, Any]:
    """按异常类型和因果链分类，不读取可能含凭据的异常文本。"""
    context: dict[str, Any] = {'error': type(exc).__name__, 'stage': stage}
    chain: list[BaseException] = []
    cause: BaseException | None = exc
    while cause is not None and cause not in chain and len(chain) < 8:
        chain.append(cause)
        cause = cause.__cause__ or cause.__context__
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        category = {404: 'http_not_found', 429: 'http_rate_limited',
                    401: 'source_access_restricted', 403: 'source_access_restricted'}.get(status, 'http_error')
        context['http_status'] = status
    elif any(isinstance(c, socket.gaierror) for c in chain):
        category = 'dns_error'
    elif isinstance(exc, httpx.TimeoutException):
        category = 'network_timeout'
    elif isinstance(exc, httpx.NetworkError):
        category = 'network_error'
    elif isinstance(exc, SQLAlchemyError):
        category = 'database_error'
        code = getattr(getattr(exc, 'orig', None), 'sqlstate', None)
        if isinstance(code, str) and re.fullmatch(r'[A-Z0-9]{5}', code):
            context['sqlstate'] = code
    elif isinstance(exc, SourceAccessError):
        category = 'source_policy_rejected'
    elif isinstance(exc, ValidationError) or stage == 'ingest' and isinstance(exc, ValueError):
        category = 'record_validation'
    elif isinstance(exc, (ValueError, KeyError, TypeError)) and stage == 'fetch':
        category = 'source_format_or_config'
    else:
        category = 'unexpected_error'
    context['category'] = category
    return context


def safe_stack(tb: TracebackType | None) -> list[dict[str, Any]]:
    """保留调用位置供定位；不用 exc_info，避免默认格式化输出敏感异常消息。"""
    frames = []
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append({'file': Path(code.co_filename).name, 'function': code.co_name, 'line': tb.tb_lineno})
        tb = tb.tb_next
    return frames[-12:]


def log_failure(logger: logging.Logger, event: str, **context: Any) -> None:
    logger.warning('%s', json.dumps({'event': event, **context}, ensure_ascii=False))
