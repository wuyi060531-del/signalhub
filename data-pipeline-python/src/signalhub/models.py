from datetime import date, datetime
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlsplit

class Skill(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    requirement: Literal['required', 'preferred', 'mentioned'] = 'mentioned'
    evidence: str = Field(min_length=1, max_length=200000)

class SkillGroup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    names: list[str] = Field(min_length=2, max_length=30)
    minimum: int = Field(ge=1, strict=True)
    requirement: Literal['required', 'preferred']
    evidence: str = Field(min_length=1, max_length=200000)

    @model_validator(mode='after')
    def valid_count(self):
        if len(set(n.casefold().strip() for n in self.names)) != len(self.names) or self.minimum > len(self.names):
            raise ValueError('技能组不可重复，最低数量不能超过选项数量')
        return self

class Salary(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    minimum: float | None = Field(default=None, ge=0)
    maximum: float | None = Field(default=None, ge=0)
    currency: str | None = None
    period: Literal['day', 'month', 'year', 'hour'] | None = None
    months: int | None = Field(default=None, ge=1, le=24)
    raw: str | None = None

    @model_validator(mode='after')
    def consistent_range(self):
        if self.minimum is not None and self.maximum is not None and self.minimum>self.maximum:
            raise ValueError('薪资下限不能高于上限')
        return self

class ExperienceRequirement(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    minimum_years: float | None = Field(default=None, ge=0, le=60)
    maximum_years: float | None = Field(default=None, ge=0, le=60)
    requirement: Literal['required', 'preferred']
    scope: Literal['work', 'related', 'unspecified']
    evidence: str = Field(min_length=1, max_length=200000)

    @field_validator('minimum_years','maximum_years',mode='before')
    @classmethod
    def not_boolean(cls,value):
        if isinstance(value,bool):raise ValueError('经验年数不能是布尔值')
        return value

    @model_validator(mode='after')
    def consistent_range(self):
        if self.minimum_years is None and self.maximum_years is None:
            raise ValueError('经验条件至少需要一个明确年数边界')
        if self.minimum_years is not None and self.maximum_years is not None and self.minimum_years > self.maximum_years:
            raise ValueError('经验下限不能高于上限')
        return self

class Location(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = None
    country: str | None = None
    province: str | None = None
    city: str | None = None
    primary: bool = False

class Item(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['job', 'opportunity', 'release']
    external_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=500)
    url: str | None = None
    body: str = Field(default='', max_length=200000)
    company: str | None = None
    company_type: Literal['central_state', 'local_state', 'private', 'foreign', 'joint_venture', 'finance', 'public_institution', 'research', 'other', 'unknown'] = 'unknown'
    country: str | None = None
    province: str | None = None
    city: str | None = None
    remote: bool | None = None
    locations: list[Location] = Field(default_factory=list, max_length=100)
    categories: list[str] = Field(default_factory=list)
    employment_type: Literal['internship', 'campus', 'full_time', 'other'] | None = None
    internship_type: str | None = None
    recruitment_batch: str | None = None
    education: Literal['high_school', 'associate', 'bachelor', 'master', 'doctor'] | None = None
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    graduation_years: list[Annotated[int, Field(strict=True, ge=2000, le=2100)]] = Field(default_factory=list, max_length=101)
    student_required: bool | None = None
    published_at: datetime | None = None
    deadline: date | None = None
    application_start: date | None = None
    skills: list[Skill] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list, max_length=100)
    unparsed_skill_conditions: list[str] = Field(default_factory=list, max_length=100)
    experience_requirements: list[ExperienceRequirement] = Field(default_factory=list, max_length=100)
    qualification_review_notes: list[str] = Field(default_factory=list, max_length=100)
    salary: Salary = Field(default_factory=Salary)
    days_per_week: int | None = Field(default=None, ge=1, le=7)
    duration_months: int | None = Field(default=None, ge=1, le=60)
    accepts_bachelor: bool | None = None
    bachelor_student_evidence: str | None = Field(default=None, max_length=200000)
    accepts_other_major: bool | None = None
    conversion: bool | None = None
    experience_required: bool | None = None
    major: str | None = None
    language: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    total_cost: str | None = None
    funding: str | None = None
    eligibility: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    version_tag: str | None = None
    source_verified_at: datetime | None = None
    source_verification_note: str | None = Field(default=None, max_length=2000)
    is_demo: bool = False

    @model_validator(mode='after')
    def consistent_dates_and_skills(self):
        if self.bachelor_student_evidence is not None:
            import re
            e=self.bachelor_student_evidence
            if e not in self.body or not re.search(r'(?:currently\s+)?pursuing\s+(?:a\s+)?bachelor|(?:本科|学士).{0,8}(?:在读|在校)|(?:在读|在校).{0,8}本科',e,re.I) or re.search(r'不接受|不招|无需|不要求|\bnot\b|\bno\b',e,re.I):
                raise ValueError('本科在读接受条件必须保留正文中明确正向的逐字证据')
        if self.source_verified_at:
            from datetime import timezone
            if self.source_verified_at.tzinfo is None or self.source_verified_at > datetime.now(timezone.utc):
                raise ValueError('核验时间需含时区且不能在未来')
            if not self.url or not self.url.startswith('https://') or not self.body.strip() or not (self.source_verification_note or '').strip():
                raise ValueError('人工核验需HTTPS官方链接、JD正文及核验说明')
        for start, end in [(self.application_start,self.deadline),(self.start_date,self.end_date)]:
            if start and end and start>end: raise ValueError('开始日期不能晚于结束/截止日期')
        for skill in self.skills:
            if not skill.evidence or skill.evidence not in self.body:
                raise ValueError('技能必须保留属于规范正文的原文证据')
        if any(type(y) is not int or not 2000 <= y <= 2100 for y in self.graduation_years):
            raise ValueError('届别需为2000–2100整数')
        if self.graduation_year is not None and self.graduation_years and self.graduation_years != [self.graduation_year]:
            raise ValueError('单届别与多届别冲突')
        for group in self.skill_groups:
            if group.evidence not in self.body:
                raise ValueError('技能组必须保留属于规范正文的原文证据')
            for name in group.names:
                from .normalize import SKILLS
                import re
                if not any(s.name == name for s in self.skills) or not re.search(SKILLS.get(name,re.escape(name)),group.evidence,re.I):
                    raise ValueError('技能组选项需在技能表与原文证据中出现')
        if any(not evidence or evidence not in self.body for evidence in self.unparsed_skill_conditions):
            raise ValueError('未解析技能条件必须保留原文证据')
        for condition in self.experience_requirements:
            if condition.evidence not in self.body:
                raise ValueError('经验条件必须保留原文证据')
        if any(not evidence or evidence not in self.body for evidence in self.qualification_review_notes):
            raise ValueError('资格复核必须保留原文证据')
        return self

    @field_validator('url')
    @classmethod
    def safe_link(cls, value):
        if value:
            p = urlsplit(value)
            if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
                raise ValueError('只接受无凭据的 http/https 链接；导入不会自动访问链接')
        return value
