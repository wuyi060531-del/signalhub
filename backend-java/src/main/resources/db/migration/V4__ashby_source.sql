-- 扩展来源类型，保留所有现有来源/岗位/任务数据，不修改已应用迁移。
ALTER TABLE sources DROP CONSTRAINT sources_adapter_check;
ALTER TABLE sources ADD CONSTRAINT sources_adapter_check
 CHECK(adapter IN ('manual','github','greenhouse','rss','ashby'));
