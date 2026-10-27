"""Both playlist landing pages expose the active evaluation without replacing tiles."""
import unittest
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]


class FeaturedTileRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Environment(loader=FileSystemLoader(str(ROOT/'templates')),
                              autoescape=True)
        cls.env.globals['url_for'] = lambda endpoint, **kw: '/' + endpoint + ('/' + str(kw['job_id']) if 'job_id' in kw else '')
        cls.job = {'source_type':'self','learning_modes':[], 'date_range':'all'}

    def render(self, name, feature):
        return self.env.get_template(name).render(
            job=self.job, job_id=1, ui_settings={}, nav_training_job_id=1,
            nav_job_id=1, evaluation_feature=feature)

    def test_new_run_appears_in_both_with_exact_link(self):
        feature={'model':'rules-v35-decision-findings','ready':True,'run_id':99,
                 'solved':0,'total':36,'href':'/trainer/1?benchmark=1&run_id=99'}
        for page in ('lessons.html','openings.html'):
            with self.subTest(page=page):
                html=self.render(page,feature)
                self.assertIn('0/36',html)
                self.assertIn('run_id=99',html)
                self.assertIn('evaluation-feature-card',html)
                self.assertIn('Continue evaluation',html)

    def test_missing_run_is_visible_with_actionable_reason(self):
        feature={'model':'rules-v35-decision-findings','ready':False,
                 'solved':0,'total':36,'href':'/processes?job_id=1',
                 'reason':'35/36 benchmark positions have current-model explanations.'}
        for page in ('lessons.html','openings.html'):
            with self.subTest(page=page):
                html=self.render(page,feature)
                self.assertIn('0/36',html)
                self.assertIn('35/36 benchmark',html)
                self.assertIn('Prepare in Process',html)

    def test_completed_run_is_not_featured(self):
        for page in ('lessons.html','openings.html'):
            with self.subTest(page=page):
                html=self.render(page,None)
                self.assertNotIn('evaluation-feature-card',html)
                self.assertIn('lesson-grid',html)


if __name__=='__main__': unittest.main()
