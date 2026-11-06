from .github import GithubAdapter
from .greenhouse import GreenhouseAdapter
from .rss import RssAdapter
from .ashby import AshbyAdapter
from .smartrecruiters import SmartRecruitersAdapter
from .lever import LeverAdapter
ADAPTERS = {'github': GithubAdapter, 'greenhouse': GreenhouseAdapter, 'rss': RssAdapter, 'ashby': AshbyAdapter, 'smartrecruiters':SmartRecruitersAdapter, 'lever':LeverAdapter}
