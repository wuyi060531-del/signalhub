"""check.sh 先运行 Java，使用真正的队列输出验证 Python 契约。"""
from pathlib import Path
import json
import pytest
from signalhub.normalize import normalize
from signalhub.pipeline import Pipeline


def test_java_serialized_import_is_accepted_by_python(db):
    path=Path(__file__).resolve().parents[2]/'backend-java/target/interop-import.json'
    if not path.exists():pytest.skip('先运行 Maven test 生成跨语言契约样本')
    record=json.loads(path.read_text())
    item=normalize(record)
    assert str(item.deadline)=='2026-12-31' and item.days_per_week==3
    assert item.salary.minimum==200 and item.salary.period=='day'
    assert item.skills[0].name=='Python'
    result=Pipeline(db).run(1,[record])
    assert result['state']=='success' and result['parsed']==1
    assert Pipeline(db).run(1,[record])['deduplicated']==1


def test_java_group_contract_reaches_python_payload(db):
    path=Path(__file__).resolve().parents[2]/'backend-java/target/interop-group-import.json'
    assert path.exists(), '需先运行Java契约测试'
    record=json.loads(path.read_text())
    item=normalize(record)
    assert item.skill_groups[0].names==['Python','Java']
    assert item.graduation_years==[2026,2027] and item.student_required is True
    p=Pipeline(db)
    assert p.run(1,[record])['inserted']==1
    assert p.run(1,[record])['deduplicated']==1


def test_java_experience_contract_evidence_and_zero_bound(db):
    path=Path(__file__).resolve().parents[2]/'backend-java/target/interop-experience-import.json'
    assert path.exists(), '需先运行Java契约测试'
    record=json.loads(path.read_text());item=normalize(record)
    assert item.experience_requirements[0].minimum_years==0
    assert item.experience_requirements[0].maximum_years==2
    assert item.qualification_review_notes==['工作经验：0-2年']
    p=Pipeline(db);assert p.run(1,[record])['inserted']==1
    assert p.run(1,[record])['deduplicated']==1
