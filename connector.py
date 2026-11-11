"""Small, dependency-free Telegram briefing sender. Dry-run unless --send is given."""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ConnectorError(Exception):
    pass


def units(text):
    return len(text.encode('utf-16-le')) // 2


def chunks(text, limit=4096):
    """Split conservatively by UTF-16 length, preserving every character."""
    part, length = [], 0
    for character in text:
        size = units(character)
        if length + size > limit:
            yield ''.join(part)
            part, length = [], 0
        part.append(character)
        length += size
    if part:
        yield ''.join(part)


def plan(document):
    if not isinstance(document, dict) or set(document) - {'title', 'items'}:
        raise ConnectorError('Expected an object containing title and items only.')
    title, items = document.get('title', ''), document.get('items')
    if not isinstance(title, str) or not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ConnectorError('title must be text; items must contain 1-50 entries.')
    result = [('sendMessage', {'text': text}) for text in chunks(title)]
    for item in items:
        if not isinstance(item, dict) or set(item) - {'text', 'source_url', 'photo_url'}:
            raise ConnectorError('Each item accepts text, source_url and optional photo_url only.')
        text = item.get('text')
        source = item.get('source_url')
        photo = item.get('photo_url')
        if not isinstance(text, str) or not text.strip():
            raise ConnectorError('Every item needs nonempty text.')
        for value in [source] + ([photo] if photo is not None else []):
            if not isinstance(value, str):
                raise ConnectorError('Every item needs an HTTPS source URL; photo URLs must also be HTTPS.')
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ConnectorError('URLs must be HTTPS without embedded credentials.')
        body = text + '\n' + source
        if photo is not None:
            payload = {'photo': photo}
            if units(body) <= 1024:
                payload['caption'] = body
            result.append(('sendPhoto', payload))
            if 'caption' in payload:
                continue
        result.extend(('sendMessage', {'text': part}) for part in chunks(body))
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ConnectorError('Unexpected redirect refused.')


def send(token, chat_id, operations, opener=None, sleep=time.sleep):
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token or ''):
        raise ConnectorError('Missing or invalid TELEGRAM_BOT_TOKEN.')
    if not re.fullmatch(r'-?[0-9]+|@[A-Za-z0-9_]+', chat_id or ''):
        raise ConnectorError('Missing or invalid TELEGRAM_CHAT_ID.')
    opener = opener or urllib.request.build_opener(NoRedirect())
    completed = []
    for method, fields in operations:
        payload = dict(fields, chat_id=chat_id)
        request = urllib.request.Request(
            'https://api.telegram.org/bot' + token + '/' + method,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with opener.open(request, timeout=30) as response:
                result = json.loads(response.read(1024 * 1024))
            if result.get('ok') is not True:
                raise ConnectorError('Telegram rejected the request.')
            message_id = result['result']['message_id']
        except Exception:
            # Never log exception strings: HTTP errors may contain the token URL.
            raise ConnectorError(
                f'Stopped after {len(completed)} confirmed messages. Last request may have arrived. '
                'Inspect the destination before retrying; no automatic retries were made.'
            ) from None
        completed.append(message_id)
        sleep(1.1)
    return completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('briefing', type=Path, help='UTF-8 JSON briefing file')
    parser.add_argument('--send', action='store_true', help='Actually send to configured Telegram chat')
    args = parser.parse_args()
    try:
        if args.briefing.stat().st_size > 1024 * 1024:
            raise ConnectorError('Briefing file must be at most 1 MB.')
        operations = plan(json.loads(args.briefing.read_text(encoding='utf-8')))
        if not args.send:
            print(json.dumps({'dry_run': True, 'messages': [
                {'method': method, **fields} for method, fields in operations
            ]}, ensure_ascii=False, indent=2))
            return 0
        ids = send(os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID'), operations)
        print(json.dumps({'sent': len(ids), 'message_ids': ids}))
        return 0
    except (ConnectorError, OSError, ValueError, TypeError, UnicodeError):
        # Only our own curated errors are safe to print.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, ConnectorError) else 'Invalid or unreadable briefing file.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
