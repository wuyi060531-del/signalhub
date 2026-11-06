import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from signalhub.normalize import normalize

SAMPLES=json.loads((Path(__file__).resolve().parents[2]/'tests/fixtures/synthetic-jd-qualifications.json').read_text())['samples']


@pytest.mark.parametrize('sample',SAMPLES,ids=[s['name'] for s in SAMPLES])
def test_synthetic_jd_qualification_annotations(sample):
    job=normalize(dict(kind='job',external_id='annotation',title=sample['title'],body=sample['body']))
    expected=sample['expected']
    for key,attr in [('education','education'),('student','student_required'),('days','days_per_week'),('months','duration_months'),('internship_experience','experience_required')]:
        if key in expected:assert getattr(job,attr)==expected[key]
    if 'minimum' in expected:
        assert len(job.experience_requirements)==1
        condition=job.experience_requirements[0]
        assert condition.minimum_years==expected['minimum'] and condition.maximum_years==expected.get('maximum')
        assert condition.scope==expected['scope'] and condition.requirement==expected.get('requirement','required')
        assert condition.evidence in job.body
    if expected.get('review'):assert job.qualification_review_notes
    if expected.get('unparsed'):assert job.unparsed_skill_conditions and all(s.requirement=='mentioned' for s in job.skills)
    if 'docker' in expected:assert next(s for s in job.skills if s.name=='Docker').requirement==expected['docker']


@pytest.mark.parametrize('body,lower,upper',[
    ('工作经验：3年以上',3,None),('Requirements；At least 2.5 years of professional experience',2.5,None),
    ('Required: up to 2 years of work experience',None,2),('工作经验：0–2年',0,2),
    ('要求至少3年工作经验',3,None),
])
def test_explicit_general_work_years_and_bounds(body,lower,upper):
    job=normalize(dict(kind='job',external_id='years',title='Engineer',body=body))
    condition=job.experience_requirements[0]
    assert (condition.minimum_years,condition.maximum_years,condition.scope)==(lower,upper,'work')
    assert not job.qualification_review_notes


@pytest.mark.parametrize('body',[
    'Our team has 10 years of professional experience', '要求5年项目经验',
    '公司成立于2020年；要求Python；实习6个月', '无需3年工作经验；要求Python',
    'Required: no previous experience with Python or Java is required',
])
def test_unknown_project_company_and_negative_years_not_guessed(body):
    assert not normalize(dict(kind='job',external_id='unknown',title='Engineer',body=body)).experience_requirements


def test_degree_preference_and_major_not_promoted_to_minimum():
    job=normalize(dict(kind='job',external_id='pref',title='Engineer',body='Preferred Qualifications；Master’s degree in Computer Science；Job Description；Build systems'))
    assert job.education is None and job.major is None
    job=normalize(dict(kind='job',external_id='major',title='Engineer',body='Requirements；Bachelor’s degree in Computer Science or related field'))
    assert job.education=='bachelor' and job.major in job.body


@pytest.mark.parametrize('body',['No prior experience with Python or Java is required','不强制要求Java和Docker，掌握Python','Required: Python is not mandatory; SQL required'])
def test_more_negative_skill_scope(body):
    skills={s.name:s.requirement for s in normalize(dict(kind='job',external_id='neg',title='Engineer',body=body)).skills}
    assert skills==({} if body.startswith('No') else {'Python':'required'} if body.startswith('不') else {'SQL':'required'})


def test_range_time_not_guessed_and_imported_evidence_validated():
    job=normalize(dict(kind='job',external_id='time-range',title='Intern',body='Work 3 - 5 days per week; Internship duration: 6-12 months'))
    assert job.days_per_week is None and job.duration_months is None
    raw=dict(kind='job',external_id='manual',title='Engineer',body='工作经验：0-2年',
             experience_requirements=[dict(minimum_years=0,maximum_years=2,scope='work',requirement='required',evidence='工作经验：0-2年')])
    assert normalize(raw).experience_requirements[0].maximum_years==2
    for change in [dict(minimum_years=3),dict(evidence='伪造'),dict(minimum_years=None,maximum_years=None),dict(scope='guess')]:
        with pytest.raises(ValidationError):normalize({**raw,'experience_requirements':[{**raw['experience_requirements'][0],**change}]})
    with pytest.raises(ValidationError):normalize({**raw,'qualification_review_notes':['伪造证据']})


def test_willingness_to_work_in_language_is_not_confirmed_mastery_requirement():
    job=normalize(dict(kind='job',external_id='willingness',title='Engineer',body='The Must-Haves:；You can be a good coder in any language, but willing to work on Golang. Proficiency in Golang will be a strong advantage.'))
    assert job.skills[0].name=='Go' and job.skills[0].requirement=='preferred'
    mixed=normalize(dict(kind='job',external_id='willing-scope',title='Engineer',body='Must know Python, willing to work on Go'))
    assert {s.name:s.requirement for s in mixed.skills}=={'Go':'mentioned','Python':'required'}


@pytest.mark.parametrize('title,body,expected',[
    ('Java 后端实习','非实习岗位，要求3年工作经验',None),
    ('Software Engineer Intern','This is not an internship.',None),
    ('Java 后端实习','本科在读，日常实习','internship'),
])
def test_explicit_non_internship_is_never_inferred_from_title(title,body,expected):
    assert normalize(dict(kind='job',external_id='scope',title=title,body=body)).employment_type==expected


def test_manual_verification_requires_full_evidence_and_timezone():
    raw=dict(kind='job',external_id='evidence',title='合成实习',url='https://example.com/synthetic',
             body='合成测试JD；本科在读；日常实习',source_verified_at='2026-01-01T00:00:00+08:00',source_verification_note='合成核验说明')
    assert normalize(raw).source_verified_at is not None
    for change in [dict(body=''),dict(url=None),dict(source_verification_note=''),dict(source_verified_at='2099-01-01T00:00:00+08:00'),dict(source_verified_at='2026-01-01T00:00:00')]:
        with pytest.raises(ValidationError):normalize({**raw,**change})
    assert normalize(dict(kind='job',external_id='url-only',title='仅有链接',url=raw['url'])).source_verified_at is None


@pytest.mark.parametrize('body,accepted',[
    ('Requirements；Pursuing Bachelor’s/Master’s degree in Computer Science or equivalent work experience', True),
    ('要求：本科在读；每周3天',True),
    ('Required: a bachelor degree in Computer Science',False),
    ('Preferred: pursuing a bachelor degree',False),
    ('不接受本科在读学生；要求硕士',False),
    ('Not pursuing a bachelor degree',False),
    ('Requirements；Currently pursuing a Bachelor\'s degree',True),
])
def test_bachelor_student_path_is_evidenced_separately_from_minimum_degree(body,accepted):
    job=normalize(dict(kind='job',external_id='pathway',title='Intern',body=body))
    assert bool(job.bachelor_student_evidence)==accepted
    if accepted:assert job.bachelor_student_evidence in job.body
    if 'equivalent' in body:assert job.education is None and job.student_required is None


def test_imported_bachelor_evidence_cannot_be_unrelated_or_negated_text():
    for evidence in ['', '要求Python','不接受本科在读学生']:
        with pytest.raises(ValidationError):
            normalize(dict(kind='job',external_id='bad-evidence',title='实习',body=evidence,bachelor_student_evidence=evidence))


def test_explicit_english_student_and_graduate_cohort():
    raw=dict(kind='job',external_id='synthetic-cohort',
             title='Application Engineer Intern - 2028 Graduates',
             body='Required: bachelor degree or master degree in software engineering；Full-time students who will graduate in 2028')
    job=normalize(raw)
    assert job.graduation_year==2028 and job.graduation_years==[2028]
    assert job.education=='bachelor' and job.student_required is True
    assert job.start_date is None and job.duration_months is None


@pytest.mark.parametrize('title,body,cohort,student',[
    ('Intern','Full-time students graduating in 2028',2028,True),
    ('Intern','Student who will graduate in 2028',2028,True),
    ('Intern','Full-time student preferred; 2028 graduates preferred',None,None),
    ('Intern','Not required to be a full-time student; no graduation year restriction',None,False),
    ('2028 AI conference intern','Event takes place in 2028',None,None),
    ('Intern','Not for 2028 graduates',None,None),
    ('Intern','Not a full-time student',None,None),
    ('Intern','2028 graduates are not eligible',None,None),
])
def test_english_cohort_student_negation_preference_and_dates_are_conservative(title,body,cohort,student):
    job=normalize(dict(kind='job',external_id='synthetic-cohort-scope',title=title,body=body))
    assert job.graduation_year==cohort and job.student_required is student
    assert job.start_date is None
