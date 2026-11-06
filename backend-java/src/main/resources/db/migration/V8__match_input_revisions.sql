-- 旧结果的输入修订无法证明，不回填为“当前”；保留结果，刷新后写入确切修订。
ALTER TABLE match_results ADD COLUMN item_version integer CHECK(item_version > 0);
ALTER TABLE match_results ADD COLUMN profile_updated_at timestamptz;
ALTER TABLE match_results ADD COLUMN engine_revision text;
