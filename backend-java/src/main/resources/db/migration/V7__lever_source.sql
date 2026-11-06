ALTER TABLE sources DROP CONSTRAINT sources_adapter_check;
ALTER TABLE sources ADD CONSTRAINT sources_adapter_check
 CHECK(adapter IN ('manual','github','greenhouse','rss','ashby','smartrecruiters','lever'));
