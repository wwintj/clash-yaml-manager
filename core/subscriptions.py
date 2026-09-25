"""Versioned subscription signatures; legacy credentials never authorize V2 files."""
import base64
import hashlib
import hmac
import re


NEW_FILENAME = re.compile(r'tim_([0-9]{8})_([1-9][0-9]{0,15})_([A-Za-z0-9_-]{22})\.yaml')
V2_SLUG = re.compile(r'v2\.([0-9]{8})\.([0-9a-z]{1,11})\.([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{22})')


def safe_filename(filename: str) -> bool:
    return (isinstance(filename, str) and 0 < len(filename) <= 255
            and filename.endswith('.yaml') and '/' not in filename
            and '\\' not in filename and '\0' not in filename)


def legacy_filename(filename: str) -> bool:
    # Reserve the entire nonce namespace, including malformed V2 names.
    return safe_filename(filename) and not re.match(r'tim_[0-9]{8}_[0-9]+_', filename)


def encode_base36(number: int) -> str:
    alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
    encoded = ''
    while number:
        number, remainder = divmod(number, 36)
        encoded = alphabet[remainder] + encoded
    return encoded or '0'


class SubscriptionSigner:
    def __init__(self, key: bytes):
        self.key = key

    def full_token(self, filename: str) -> str:
        # Keep the historical full HMAC stable for existing subscriptions.
        return hmac.new(self.key, filename.encode('utf-8'), hashlib.sha256).hexdigest()

    def valid_full_token(self, filename: str, token: str) -> bool:
        return bool(safe_filename(filename) and isinstance(token, str)
                    and re.fullmatch(r'[0-9a-f]{64}', token)
                    and hmac.compare_digest(token, self.full_token(filename)))

    def valid_legacy_token(self, filename: str, token: str) -> bool:
        return bool(legacy_filename(filename) and isinstance(token, str)
                    and re.fullmatch(r'(?:[0-9a-f]{8}|[0-9a-f]{12})', token)
                    and hmac.compare_digest(token, self.full_token(filename)[:len(token)]))

    def v2_signature(self, filename: str) -> str:
        digest = hmac.new(self.key, b'subscription-v2\0' + filename.encode('utf-8'), hashlib.sha256).digest()[:16]
        return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')

    def valid_v2_signature(self, filename: str, signature: str) -> bool:
        return bool(NEW_FILENAME.fullmatch(filename) and isinstance(signature, str)
                    and re.fullmatch(r'[A-Za-z0-9_-]{22}', signature)
                    and hmac.compare_digest(signature, self.v2_signature(filename)))

    def build_slug(self, filename: str) -> str:
        match = NEW_FILENAME.fullmatch(filename)
        if match:
            date, count, nonce = match.groups()
            return f'v2.{date}.{encode_base36(int(count))}.{nonce}.{self.v2_signature(filename)}'
        if not legacy_filename(filename):
            raise ValueError('Invalid subscription filename.')
        signature = self.full_token(filename)[:8]
        match = re.fullmatch(r'tim_([0-9]{8})_([0-9]+)\.yaml', filename)
        if match:
            date, count = match.groups()
            return f'{date[2:]}{encode_base36(int(count))}{signature}'
        return f'{filename[:-5]}-{signature}'

    def parse_slug(self, slug: str) -> tuple[str, str]:
        if not isinstance(slug, str) or len(slug) > 320 or '/' in slug or '\\' in slug:
            return '', ''
        if slug.startswith('v2.'):
            match = V2_SLUG.fullmatch(slug)
            if not match:
                return '', ''
            date, count, nonce, signature = match.groups()
            number = int(count, 36)
            filename = f'tim_{date}_{number}_{nonce}.yaml'
            if encode_base36(number) == count and self.valid_v2_signature(filename, signature):
                return filename, signature
            return '', ''
        match = re.fullmatch(r'([0-9]{6})([0-9a-z]+)([0-9a-f]{8})', slug)
        if match:
            date, count, signature = match.groups()
            filename = f'tim_20{date}_{int(count, 36)}.yaml'
        elif '-' in slug:
            stem, signature = slug.rsplit('-', 1)
            filename = f'{stem}.yaml'
        else:
            return '', ''
        if legacy_filename(filename) and (self.valid_legacy_token(filename, signature)
                                          or self.valid_full_token(filename, signature)):
            return filename, signature
        return '', ''
