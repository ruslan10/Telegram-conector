import io
import json
import unittest
from unittest.mock import Mock
from connector import ConnectorError, chunks, plan, send, units


class Tests(unittest.TestCase):
    def sample(self, **extra):
        return {'title': 'שלום', 'items': [dict(text='בדיקה', source_url='https://example.com', **extra)]}

    def test_hebrew_and_source(self):
        self.assertEqual(plan(self.sample())[1], ('sendMessage', {'text': 'בדיקה\nhttps://example.com'}))

    def test_short_photo_caption(self):
        self.assertIn('caption', plan(self.sample(photo_url='https://example.com/photo.png'))[1][1])

    def test_long_photo_separate_text(self):
        data = self.sample(photo_url='https://example.com/photo.png')
        data['items'][0]['text'] = 'א' * 1100
        ops = plan(data)
        self.assertNotIn('caption', ops[1][1])
        self.assertEqual(ops[2][0], 'sendMessage')

    def test_split_emoji_roundtrip(self):
        text = 'שלום 🐱\n' * 2000
        parts = list(chunks(text))
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(units(part) <= 4096 for part in parts))

    def test_validation(self):
        for value in [None, {}, {'items': []}, {'items': [{'text': 'x'}]},
                      {'items': [{'text': 'x', 'source_url': 'http://example.com'}]}]:
            with self.assertRaises(ConnectorError):
                plan(value)

    def test_no_destination_override(self):
        data = self.sample()
        data['items'][0]['chat_id'] = '123'
        with self.assertRaises(ConnectorError):
            plan(data)

    def test_send_mock(self):
        response = io.BytesIO(json.dumps({'ok': True, 'result': {'message_id': 10}}).encode())
        opener = Mock()
        opener.open.return_value = response
        self.assertEqual(send('123:test', '@example', [('sendMessage', {'text': 'hi'})], opener, lambda _: None), [10])
        body = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(body['chat_id'], '@example')
        self.assertNotIn('allow_paid_broadcast', body)

    def test_errors_redacted_no_retry(self):
        opener = Mock()
        opener.open.side_effect = RuntimeError('secret-token-in-url')
        with self.assertRaises(ConnectorError) as caught:
            send('123:test', '@example', [('sendMessage', {'text': 'hi'})], opener)
        self.assertNotIn('secret-token', str(caught.exception))
        self.assertEqual(opener.open.call_count, 1)


if __name__ == '__main__':
    unittest.main()
