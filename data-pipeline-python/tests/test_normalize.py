import pytest
from pydantic import ValidationError
from signalhub.normalize import normalize,parse_salary,canonical_url,content,stable_hash

@pytest.mark.parametrize('salary,low,high,period,months',[
 ('200 元/天',200,200,'day',None),('5k/月',5000,5000,'month',None),('15k–25k/月',15000,25000,'month',None),('20k–30k/月·14薪',20000,30000,'month',14),('20k–30k·14薪',20000,30000,'month',14),('面议',None,None,None,None)])
def test_salary(salary,low,high,period,months):
    result=parse_salary(salary)
    assert (result.minimum,result.maximum,result.period,result.months)==(low,high,period,months)

def test_cohort_is_not_publication_year():
    job=normalize(dict(kind='job',external_id='a',title='实习',body='2026年发布；2027届本科生；要求 Python、SQL；Spark 加分'))
    assert job.graduation_year==2027 and job.education=='bachelor'
    assert job.employment_type=='internship'
    assert {s.name:s.requirement for s in job.skills}=={'Python':'required','SQL':'required','Spark':'preferred'}
    assert normalize(dict(kind='job',external_id='b',title='2026年招聘')).graduation_year is None

def test_unknown_conditions_are_null():
    job=normalize(dict(kind='job',external_id='a',title='Data Engineer'))
    assert job.country is None and job.education is None and job.deadline is None
    assert job.salary.minimum is None and job.accepts_bachelor is None
    assert 'data_engineering' in job.categories

def test_html_and_formatting_not_change_content():
    a=normalize(dict(kind='job',external_id='a',title='Java',body='<p>要求 Java SQL</p>'))
    b=normalize(dict(kind='job',external_id='b',title='Java',body='要求  Java   SQL'))
    assert stable_hash(content(a))==stable_hash(content(b))
    assert '<script>' not in normalize(dict(kind='job',external_id='c',title='x',body='<script>alert(1)</script>Python')).body

def test_unsafe_links_rejected():
    with pytest.raises(ValidationError): normalize(dict(kind='job',external_id='a',title='x',url='javascript:alert(1)'))
    assert canonical_url('https://example.com/a?utm_source=x&id=1#hi')=='https://example.com/a?id=1'

def test_encoded_html_and_requirement_boundaries():
    job=normalize(dict(kind='job',external_id='html',title='Data Engineer',body='&lt;p&gt;Required: &lt;b&gt;Python&lt;/b&gt;, SQL&lt;/p&gt;&lt;p&gt;Spark preferred&lt;/p&gt;&lt;script&gt;bad()&lt;/script&gt;'))
    assert '<' not in job.body and 'bad()' not in job.body
    assert {s.name:s.requirement for s in job.skills}=={'Python':'required','SQL':'required','Spark':'preferred'}

def test_explicit_dates_and_ambiguous_cohorts():
    job=normalize(dict(kind='job',external_id='dates',title='2026/2027届秋招',body='发布于2026年10月13日；申请开始：2026-10-01；申请截止：2026年12月31日；专业要求：数据科学；英语要求：CET-6'))
    assert job.graduation_year is None
    assert str(job.deadline)=='2026-12-31' and str(job.application_start)=='2026-10-01'
    assert job.major=='数据科学' and job.language=='CET-6' and job.recruitment_batch=='秋招'
    assert normalize(dict(kind='job',external_id='date2',title='Class of 2027',body='published 2026-10-13; deadline: 2026-02-31')).deadline is None
    assert normalize(dict(kind='job',external_id='date3',title='Class of 2027')).graduation_year==2027

def test_invalid_structured_ranges_and_skill_claims():
    for extra in [dict(salary={'minimum':300,'maximum':200}),dict(deadline='2026-01-01',application_start='2026-02-01'),dict(skills=[{'name':'Java','evidence':'要求 Java'}])]:
        with pytest.raises(ValidationError): normalize(dict(kind='job',external_id='invalid',title='Job',body='要求 Python',**extra))

def test_negative_skill_mentions_not_counted_as_requirements():
    job=normalize(dict(kind='job',external_id='negation',title='实习',body='不要求 Java；无需 Docker 经验；Python 不属于岗位技能要求；Required: SQL. Spark preferred. SQL required.'))
    assert {s.name:s.requirement for s in job.skills}=={'SQL':'required','Spark':'preferred'}

def test_structured_skill_aliases_are_unique_and_keep_required():
    job=normalize(dict(kind='job',external_id='aliases',title='实习',body='要求 Python；Python优先',skills=[{'name':'python','evidence':'Python优先','requirement':'preferred'},{'name':'Python','evidence':'要求 Python','requirement':'required'}]))
    assert len(job.skills)==1 and job.skills[0].name=='Python' and job.skills[0].requirement=='required'

def test_chinese_adjacent_skill_tokens_and_javascript_not_java():
    job=normalize(dict(kind='job',external_id='bilingual',title='AI实习岗位',body='熟悉Python和SQL；JavaScript开发；SpringBoot优先；有Docker经验；SQLAlchemy框架'))
    assert {s.name for s in job.skills}=={'Python','SQL','Spring Boot','Docker'}
    assert 'java_backend' not in job.categories and 'ai' in job.categories

@pytest.mark.parametrize('body',[
    '不要求Java和Docker，掌握Python和SQL',
    'No need for Java and Docker; Required: Python SQL',
    'Java and Docker are not required; Required: Python SQL',
])
def test_negation_spans_skill_list_but_stops_at_new_requirement(body):
    job=normalize(dict(kind='job',external_id='negative-list',title='Job',body=body))
    assert {s.name:s.requirement for s in job.skills}=={'Python':'required','SQL':'required'}

@pytest.mark.parametrize('body',[
    '熟练掌握C/C++/Python任意两种编程语言',
    '要求掌握Python、Java、SQL中的任意两种',
    'Required: either Python or Java',
])
def test_skill_alternatives_not_each_individually_required(body):
    job=normalize(dict(kind='job',external_id='alternatives',title='Job',body=body))
    assert job.skills and all(s.requirement=='mentioned' for s in job.skills)
    # 另一句明确要求仍有独立证据，不能被前一句任选规则抵消。
    explicit=normalize(dict(kind='job',external_id='explicit',title='Job',body=body+'；必须掌握Python'))
    assert next(s for s in explicit.skills if s.name=='Python').requirement=='required'


@pytest.mark.parametrize('body,names,minimum',[
 ('要求掌握Python、Java、SQL中的任意两种',['Python','Java','SQL'],2),
 ('Required: either Python or Java',['Python','Java'],1),
 ('熟练掌握C/C++/Python任意两种编程语言',['C','C++','Python'],2),
 ('Proficient in at least one programming language, such as Python, Go, or Java.',['Python','Go','Java'],1),
])
def test_explicit_skill_groups_keep_count_and_verbatim_evidence(body,names,minimum):
    job=normalize(dict(kind='job',external_id='group',title='Job',body=body))
    assert len(job.skill_groups)==1
    g=job.skill_groups[0]
    assert g.names==names and g.minimum==minimum and g.requirement=='required'
    assert g.evidence in job.body
    assert all(s.requirement=='mentioned' for s in job.skills)


def test_inline_required_preferred_negative_and_group_scope():
    job=normalize(dict(kind='job',external_id='mixed',title='Job',body='要求 Python，SQL加分；不要求Docker和Java，掌握Spark；Required: either Python or Java, SQL required'))
    assert {s.name:s.requirement for s in job.skills}=={'Python':'required','SQL':'required','Spark':'required','Java':'mentioned'}
    assert job.skill_groups[0].names==['Python','Java']
    assert job.skill_groups[0].evidence=='Required: either Python or Java'
    pref=normalize(dict(kind='job',external_id='pref',title='Job',body='Preferred Qualifications:；Python and SQL；Job Description:；Java project'))
    assert {s.name:s.requirement for s in pref.skills}=={'Python':'preferred','SQL':'preferred','Java':'mentioned'}


@pytest.mark.parametrize('body',['要求Python、Java、Rust任意两种','Required: either Python, Rust or Java','No need for either Python or Java'])
def test_unsupported_or_negated_group_does_not_invent_complete_condition(body):
    assert not normalize(dict(kind='job',external_id='unsupported',title='Job',body=body)).skill_groups


def test_multiple_cohorts_student_and_negative_degree():
    job=normalize(dict(kind='job',external_id='qualification',title='2026-2028届实习生',body='不接受本科生；硕士在读；无需实习经验；每周到岗3天；实习至少6个月'))
    assert job.graduation_year is None and job.graduation_years==[2026,2027,2028]
    assert job.education=='master' and job.accepts_bachelor is False and job.student_required is True
    assert job.experience_required is False and job.days_per_week==3 and job.duration_months==6
    assert normalize(dict(kind='job',external_id='no-student',title='实习',body='不要求在校生')).student_required is False


def test_manual_groups_are_validated_and_aliases_normalized():
    raw=dict(kind='job',external_id='manual-groups',title='Job',body='要求 python 或 JAVA 任选一项',skill_groups=[dict(names=['python','JAVA'],minimum=1,requirement='required',evidence='要求 python 或 JAVA 任选一项')])
    assert normalize(raw).skill_groups[0].names==['Python','Java']
    for change in [dict(minimum=3),dict(names=['Python','python']),dict(evidence='伪造证据'),dict(minimum=True),dict(names=['Python','SQL'])]:
        with pytest.raises((ValidationError,ValueError)):
            normalize({**raw,'skill_groups':[{**raw['skill_groups'][0],**change}]})
    with pytest.raises(ValidationError):normalize({**raw,'graduation_year':2027,'graduation_years':[2026,2027]})


def test_mentoring_and_negative_intern_mentions_do_not_classify_regular_job():
    for body in ['Mentor interns and junior developers','不招聘实习生，要求Python','无需实习经验；要求SQL']:
        assert normalize(dict(kind='job',external_id='regular',title='Data Engineer',body=body)).employment_type is None


def test_plain_or_and_ambiguous_boolean_combinations_are_conservative():
    assert normalize(dict(kind='job',external_id='or',title='Job',body='必须熟悉Python或Java')).skill_groups[0].minimum==1
    ambiguous=normalize(dict(kind='job',external_id='ambiguous',title='Job',body='Required: either Python and SQL or Java'))
    assert not ambiguous.skill_groups and all(s.requirement=='mentioned' for s in ambiguous.skills)
    assert not normalize(dict(kind='job',external_id='rust-prefix',title='Job',body='Required: one of Rust, Python, Java')).skill_groups
    assert not normalize(dict(kind='job',external_id='go-verb',title='Job',body='You will go to Shanghai')).skills


def test_negated_cohort_and_english_multi_cohort_not_guessed():
    assert normalize(dict(kind='job',external_id='cohort-neg',title='实习',body='不接受2027届；面向2026届')).graduation_years==[2026]
    assert normalize(dict(kind='job',external_id='cohort-en',title='Class of 2026 or 2027 internship')).graduation_years==[2026,2027]


def test_preferred_cohort_is_not_a_hard_graduation_constraint():
    for body in ['计算机相关专业本科或硕士在读，2027届毕业生优先',
                 'Preferred qualifications: Class of 2027',
                 'Preferred qualifications:\nClass of 2027',
                 '2026-2028届优先；本科在读']:
        job=normalize(dict(kind='job',external_id='cohort-preferred',title='实习生',body=body,is_demo=True))
        assert job.graduation_year is None and not job.graduation_years
        assert '2027' in job.body or '2026' in job.body
    job=normalize(dict(kind='job',external_id='cohort-mixed',title='实习生',body='面向2026届；2027届优先',is_demo=True))
    assert job.graduation_year==2026 and job.graduation_years==[2026]
    for body in ['仅限2027届本科在读，具备开发项目经历优先',
                 '面向2027届毕业生，计算机相关专业优先',
                 'Class of 2027, Python experience preferred']:
        job=normalize(dict(kind='job',external_id='cohort-required',title='实习生',body=body,is_demo=True))
        assert job.graduation_year==2027 and job.graduation_years==[2027]


def test_structured_group_normalization_does_not_mutate_raw():
    import copy
    raw=dict(kind='job',external_id='immutable',title='Job',body='python或JAVA任选一项',skill_groups=[dict(names=['python','JAVA'],minimum=1,requirement='required',evidence='python或JAVA任选一项')])
    before=copy.deepcopy(raw)
    normalize(raw)
    assert raw==before


def test_unrelated_or_does_not_downgrade_explicit_required_skill():
    job=normalize(dict(kind='job',external_id='or-prose',title='Job',body='Python required for analytics or reporting'))
    assert job.skills[0].requirement=='required' and not job.skill_groups


def test_team_language_description_does_not_become_required_group():
    job=normalize(dict(kind='job',external_id='team-stack',title='Job',body='团队使用Python或Java'))
    assert not job.skill_groups and all(s.requirement=='mentioned' for s in job.skills)


def test_unparsed_requirement_preserves_evidence_for_information_insufficient():
    job=normalize(dict(kind='job',external_id='uncertain',title='Job',body='Required: one of Rust, Python, Java'))
    assert not job.skill_groups and job.unparsed_skill_conditions==[job.body]
    assert not normalize(dict(kind='job',external_id='plain',title='Job',body='团队使用Python或Java')).unparsed_skill_conditions


@pytest.mark.parametrize('body,expected', [
    ('Applications close: 18 Sep 2026 2359 SGT', '2026-09-18'),
    ('Application deadline: September 18, 2026 at 23:59 SGT', '2026-09-18'),
    ('Apply by 18th September 2026', '2026-09-18'),
    ('Applications close on Sept. 18 2026', '2026-09-18'),
    ('Applications close: 31 Feb 2026', None),
    ('Applications close: 18 Sep', None),
    ('Internship starts May 2027; Published Sep 18 2026', None),
    ('Deadline: 2026-09-18; Deadline: 19 September 2026', None),
])
def test_explicit_english_deadline_is_not_missing_or_guessed(body,expected):
    job=normalize(dict(kind='job',external_id='deadline-review',title='Intern',body=body))
    assert (job.deadline.isoformat() if job.deadline else None)==expected
    assert job.graduation_year is None and not job.graduation_years
