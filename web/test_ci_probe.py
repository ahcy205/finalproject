from django.test import SimpleTestCase


class CiProbeTests(SimpleTestCase):
    """CI가 실패를 잡아내는지 확인하기 위한 임시 테스트 (머지 전 삭제)."""

    def test_intentional_failure(self):
        self.assertEqual(1, 2)
