"""로그인 유지(쿠키). Secrets 의 LOGIN_KEY 가 있을 때만 켜진다.
- 로그인할 때 '아이디|만료시각|비밀번호지문'에 서명한 확인 표시를 브라우저 쿠키로 24시간 둔다.
- 화면이 새로 열려도 쿠키가 맞으면 로그인 화면을 건너뛴다. 비밀번호를 바꾸면 이전 표시는 무효가 된다.
- 쿠키는 이 브라우저에만 있고, 서명 키(LOGIN_KEY)를 모르면 만들 수 없다."""
import base64
import hashlib
import hmac
import time

PERSIST_VERSION = '2026-11-23a'
COOKIE = 'mb_auth'
TTL = 24 * 3600


def _b64(s):
    return base64.urlsafe_b64encode(s.encode('utf-8')).decode('ascii').rstrip('=')


def _unb64(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)).decode('utf-8')


def _fp(secret_part):
    return hashlib.sha256(('fp:' + str(secret_part)).encode('utf-8')).hexdigest()[:10]


def _sig(key, body):
    return hmac.new(key.encode('utf-8'), body.encode('ascii'), hashlib.sha256).hexdigest()[:40]


def make_token(user, secret_part, key, ttl=TTL, now=None):
    body = _b64(f"{user}|{int((now or time.time()) + ttl)}|{_fp(secret_part)}")
    return body + '.' + _sig(key, body)


def read_token(token, key, now=None):
    """유효하면 (아이디, 지문) 을, 아니면 None."""
    try:
        body, sig = token.split('.', 1)
        if not hmac.compare_digest(sig, _sig(key, body)):
            return None
        user, exp, fp = _unb64(body).rsplit('|', 2)
        if int(exp) < (now or time.time()):
            return None
        return user, fp
    except Exception:
        return None


def verify(token, key, secret_lookup, now=None):
    """secret_lookup(user) -> 지금 그 사용자의 비밀번호(또는 접속 코드 지문 재료). 맞으면 아이디."""
    r = read_token(token, key, now)
    if not r:
        return None
    user, fp = r
    cur = secret_lookup(user)
    if cur is None or _fp(cur) != fp:
        return None
    return user


def cookie_js(token, max_age):
    t = token or ''
    return ("<script>(function(){var s=location.protocol==='https:'?'; Secure':'';"
            f"document.cookie='{COOKIE}={t}; path=/; max-age={int(max_age)}; SameSite=Lax'+s;}})();</script>")


def run_js(st, js_html):
    """화면에 보이지 않는 자바스크립트를 한 번 실행한다(Streamlit 버전에 따라 두 방법을 차례로 쓴다)."""
    try:
        st.html(js_html, unsafe_allow_javascript=True)
    except TypeError:
        import streamlit.components.v1 as comp
        comp.html(js_html, height=0)
