from pathlib import Path
import json
import unittest
from urllib.parse import urlencode
from jinja2 import Environment, FileSystemLoader
from lxml import html

P = Path(__file__).resolve().parents[1]
class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.env = Environment(loader=FileSystemLoader(P/'templates'), autoescape=True)
        self.env.globals['url_for'] = lambda name, **args: '/' + name + (('/' + str(args['job_id'])) if 'job_id' in args else '') + (('?' + urlencode({k:v for k,v in args.items() if k!='job_id'})) if args and any(k!='job_id' for k in args) else '')
    def test_opening_detail(self):
        text = self.env.get_template('opening_detail.html').render(
            job_id=1, nav_job_id=1, ui_settings={}, opening={'key':'sicilian-defense','name':'Sicilian Defense','eco':'Multiple ECOs'},
            rating_min=900,rating_max=2500,
            variations=[{'variation':'Najdorf Variation','positions':3},{'variation':'','positions':2}],
            historical_games=[{'title':'Sample','year':1900,'players':'P1 / P2','lesson':'Check!','notable':'Nf3','source_url':'https://example.org'}],
            opening_lines=[{'opening_history':json.dumps(['e4','c5','Nf3','d6'])}])
        doc=html.fromstring(text)
        self.assertEqual(len(doc.xpath('//*[@id="position-concept-filter"]')),1)
        self.assertEqual(doc.xpath('//*[@id="position-sort"]/option')[0].get('value'),'move-asc')
        raw=doc.xpath('//*[@id="opening-tree"]')[0].get('data-lines')
        self.assertEqual(json.loads(raw)[0]['opening_history'],json.dumps(['e4','c5','Nf3','d6']))
        self.assertIn('Sicilian Defense',text)
    def test_openings(self):
        text=self.env.get_template('openings.html').render(job_id=1,nav_job_id=1,ui_settings={},job={'id':1})
        self.assertIn('OPENING PLAYLISTS',text)
        self.assertIn('opening-list',text)
if __name__=='__main__':unittest.main()
