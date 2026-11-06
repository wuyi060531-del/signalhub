import logging
import time
from typing import Any
from sqlalchemy import text
from .pipeline import Pipeline, execute, dump
from .ai.service import AIService
from .diagnostics import failure_context, safe_stack, log_failure
log = logging.getLogger(__name__)

class Worker:
    def __init__(self, engine):
        self.engine = engine
        self._queue_error_logged_at: float | None = None
        from .local_translation import LocalTranslationWorker
        self.translations = LocalTranslationWorker(engine)

    def tick(self) -> dict[str, Any] | None:
        try:
            result = self._tick()
            self._queue_error_logged_at = None
            return result
        except Exception as exc:
            # claim/终态写回也可能失败；不让调度器默认堆栈泄漏SQL参数或连接信息。
            diagnostic = failure_context(exc, stage='task_queue')
            now = time.monotonic()
            if self._queue_error_logged_at is None or now - self._queue_error_logged_at >= 60:
                log_failure(log, 'queue_failed', **diagnostic, stack=safe_stack(exc.__traceback__))
                self._queue_error_logged_at = now
            return {'state': 'failed', **diagnostic}

    def _tick(self):
        with self.engine.begin() as conn:
            # 租约超过 15 分钟视为中断；最多三次。不静默遗留 running 状态。
            execute(conn,"UPDATE task_requests SET state=CASE WHEN attempts<3 THEN 'pending' ELSE 'failed' END,error='执行租约超时',finished_at=CASE WHEN attempts>=3 THEN now() ELSE NULL END WHERE state='running' AND started_at<now()-interval '15 minutes'")
            execute(conn,"UPDATE collection_runs SET state='interrupted',ended_at=now() WHERE state='running' AND started_at<now()-interval '15 minutes'")
            task = execute(conn,"SELECT * FROM task_requests WHERE state='pending' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1").mappings().first()
            if task:
                task = dict(task)
                task['attempt']=execute(conn,"UPDATE task_requests SET state='running',attempts=attempts+1,started_at=now(),finished_at=NULL,error=NULL,result=NULL WHERE id=:id RETURNING attempts",id=task['id']).scalar_one()
        if not task:return self.translations.tick()
        try:
            if task['task_type'] == 'enrich': result = AIService(self.engine).enrich(task['payload']['item_id'])
            else:
                result = Pipeline(self.engine).run(task['source_id'],task['payload'].get('records') if task['task_type']=='import' else None)
            state = 'done' if result.get('state') not in ('failed','partial','blocked') else 'failed'
            if result.get('retryable') and task['attempt']<3:state='pending'
            with self.engine.begin() as conn:
                changed=execute(conn,"UPDATE task_requests SET state=:state,result=CAST(:result AS jsonb),finished_at=CASE WHEN :state='pending' THEN NULL ELSE now() END WHERE id=:id AND state='running' AND attempts=:attempt",state=state,result=dump(result),id=task['id'],attempt=task['attempt']).rowcount
            if not changed:return {'state':'superseded','task_id':task['id']}
            return result
        except Exception as exc:
            # 数据库不可用时不将数据丢弃，恢复后由租约重试。
            diagnostic = failure_context(exc, stage='task_execute')
            log_failure(log, 'task_failed', task_id=task['id'], source_id=task['source_id'],
                        attempt=task['attempt'], **diagnostic, stack=safe_stack(exc.__traceback__))
            with self.engine.begin() as conn:
                changed=execute(conn,"UPDATE task_requests SET state=CASE WHEN attempts<3 THEN 'pending' ELSE 'failed' END,error=:error,finished_at=CASE WHEN attempts>=3 THEN now() ELSE NULL END WHERE id=:id AND state='running' AND attempts=:attempt",error=dump(diagnostic),id=task['id'],attempt=task['attempt']).rowcount
            if not changed:return {'state':'superseded','task_id':task['id']}
            return {'state':'failed', **diagnostic}
