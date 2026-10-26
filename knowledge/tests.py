from django.test import TestCase
from django.urls import reverse

from knowledge import sources


class RegulationDataTests(TestCase):
    """knowledge/data의 규칙·안내 자료 형식."""

    def articles(self, doc):
        return [a for section in doc['sections'] for a in section['articles']]

    def test_rules_have_every_article_and_the_penalty_table(self):
        doc = sources.load('rules')
        numbers = [a.get('number') for a in self.articles(doc)]
        self.assertEqual(numbers, [str(n) for n in range(1, 15)] + ['14-2', '15', None])  # 마지막은 부칙
        self.assertEqual(len(doc['penalty_table']['rows']), 24)
        self.assertEqual(len(doc['notes']), 3)

    def test_info_has_eight_chapters_and_27_articles(self):
        doc = sources.load('info')
        self.assertEqual(len(doc['sections']), 8)
        self.assertEqual([a['number'] for a in self.articles(doc)], [str(n) for n in range(1, 28)])

    def test_every_article_has_text(self):
        for page in sources.REGULATION_PAGES:
            for article in self.articles(sources.load(page)):
                self.assertTrue(article['lines'], f'{page} {article["title"]}')
                self.assertTrue(all(isinstance(line, str) and line.strip() for line in article['lines']))

    def test_unknown_page_is_rejected(self):
        with self.assertRaises(ValueError):
            sources.load('../settings')


class RegulationPagesTests(TestCase):
    """화면이 데이터 파일의 내용을 그대로 보여 준다."""

    def test_pages_show_every_article_from_the_data(self):
        for page, url_name in (('rules', 'web:rules'), ('info', 'web:info')):
            html = self.client.get(reverse(url_name)).content.decode()
            doc = sources.load(page)
            for section in doc['sections']:
                for article in section['articles']:
                    self.assertIn(f'<strong>{article["title"]}</strong>', html)

    def test_rules_page_shows_the_penalty_table(self):
        response = self.client.get(reverse('web:rules'))
        self.assertContains(response, '<td>관내 흡연</td><td>퇴관</td>')
        self.assertContains(response, '1시간당 2점 감면')

    def test_quotes_are_escaped_safely(self):
        # 데이터의 큰따옴표는 HTML 엔티티로 나가고, 화면에는 똑같이 보인다
        self.assertContains(self.client.get(reverse('web:rules')), '(이하 &quot;관생&quot;이라 한다)')
