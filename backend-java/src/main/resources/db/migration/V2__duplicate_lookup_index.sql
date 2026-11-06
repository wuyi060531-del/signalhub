-- 低置信度候选查找使用相同标题/企业/城市；避免每条导入扫描全表。
CREATE INDEX idx_items_duplicate_lookup ON items(title,company_id,city,kind,is_demo);
