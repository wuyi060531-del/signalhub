-- 旧记录无可靠方式字段，保留legacy；不按来源类型猜历史运行方式。
ALTER TABLE collection_runs ADD COLUMN mode text NOT NULL DEFAULT 'legacy'
 CHECK(mode IN ('legacy','collect','import','archive_reparse'));
